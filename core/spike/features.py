"""Causal spike features (REQ-SPK-2, REQ-AUD-4, design section 9).

Every feature uses ONLY observations with ts_utc < cp_utc (strict causality).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import polars as pl

from core.io.timeutil import cp_to_utc, day_local_window


# Documented feature set (frozen).
SPIKE_FEATURE_COLUMNS: tuple[str, ...] = (
    "time_since_new_max_min",
    "slope_3h_c_per_h",
    "slope_6h_c_per_h",
    "wind_change_3h_deg",
    "wind_speed_latest_kt",
    "qnh_delta_3h_hpa",
    "vis_km",
    "ceiling_m",
    "wx_clearing_flag",
    "wx_rain_flag",
    "precip_3h_mm",
    "dwp_tmp_diff_c",
    "nwp_disagreement_score",
    "regime_id",
)


def _filter_causal(obs: pl.DataFrame, cp_utc: datetime) -> pl.DataFrame:
    """Return obs with ts_utc strictly < cp_utc, sorted ascending."""
    return obs.filter(pl.col("ts_utc") < cp_utc).sort("ts_utc")


def _slope(sub: pl.DataFrame, cp_utc: datetime, hours: int) -> float | None:
    """OLS slope (degC/h) over [cp - hours, cp) on tmpf -> degC."""
    if "tmpf" not in sub.columns:
        return None
    cutoff = cp_utc - timedelta(hours=hours)
    window = sub.filter(
        (pl.col("ts_utc") >= cutoff) & (pl.col("ts_utc") < cp_utc)
    ).select(["ts_utc", "tmpf"]).drop_nulls()
    if window.height < 2:
        return None
    t0 = window["ts_utc"][0]
    xs = [(t - t0).total_seconds() / 60.0 for t in window["ts_utc"].to_list()]
    tmpf_vals = window["tmpf"].to_list()
    ys = [(v - 32.0) * 5.0 / 9.0 for v in tmpf_vals]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return (num / den) * 60.0  # per hour


def build_spike_features(
    observations: pl.DataFrame,
    *,
    date_local: date,
    cp_hhmm: str,
    tz_name: str,
) -> dict[str, Any]:
    """Build causal spike feature dict for a single (date, cp).

    Raises RuntimeError on causality violation.
    """
    cp_utc = cp_to_utc(date_local, cp_hhmm)
    day_start_utc, _ = day_local_window(date_local, tz_name=tz_name)

    # STRICT causality guard (REQ-AUD-4)
    sub = _filter_causal(observations, cp_utc)
    if sub.height > 0:
        max_ts = sub["ts_utc"].max()
        assert max_ts < cp_utc, (
            f"Causality violation: max_ts={max_ts} >= cp_utc={cp_utc}"
        )

    sub_today = sub.filter(pl.col("ts_utc") >= day_start_utc)

    feats: dict[str, Any] = {}

    # time_since_new_max_min: minutes since the running max was last updated
    if sub_today.height > 0 and "tmp_c_int" in sub_today.columns:
        temps = sub_today["tmp_c_int"].to_list()
        ts_list = sub_today["ts_utc"].to_list()
        running_max = temps[0]
        last_new_max_ts = ts_list[0]
        for t_val, t_ts in zip(temps, ts_list):
            if t_val is not None and t_val >= running_max:
                running_max = t_val
                last_new_max_ts = t_ts
        feats["time_since_new_max_min"] = int(
            (cp_utc - last_new_max_ts).total_seconds() // 60
        )
    else:
        feats["time_since_new_max_min"] = None

    # slopes
    feats["slope_3h_c_per_h"] = _slope(sub, cp_utc, 3)
    feats["slope_6h_c_per_h"] = _slope(sub, cp_utc, 6)

    # wind change over 3h
    cutoff_3h = cp_utc - timedelta(hours=3)
    if sub.height > 0 and "drct" in sub.columns:
        recent = sub.filter(pl.col("ts_utc") >= cutoff_3h).select("drct").drop_nulls()
        if recent.height >= 2:
            first_dir = float(recent["drct"][0])
            last_dir = float(recent["drct"][-1])
            diff = abs(last_dir - first_dir)
            feats["wind_change_3h_deg"] = min(diff, 360.0 - diff)
        else:
            feats["wind_change_3h_deg"] = None
    else:
        feats["wind_change_3h_deg"] = None

    # wind speed latest
    if sub.height > 0 and "sknt" in sub.columns:
        last_wind = sub.select("sknt").drop_nulls()
        feats["wind_speed_latest_kt"] = (
            float(last_wind["sknt"][-1]) if last_wind.height > 0 else None
        )
    else:
        feats["wind_speed_latest_kt"] = None

    # QNH delta 3h
    if sub.height > 0 and "alti" in sub.columns:
        recent_alti = sub.filter(pl.col("ts_utc") >= cutoff_3h).select(
            ["ts_utc", "alti"]
        ).drop_nulls(subset=["alti"])
        if recent_alti.height >= 2:
            first_hpa = float(recent_alti["alti"][0]) * 33.8639
            last_hpa = float(recent_alti["alti"][-1]) * 33.8639
            feats["qnh_delta_3h_hpa"] = last_hpa - first_hpa
        else:
            feats["qnh_delta_3h_hpa"] = None
    else:
        feats["qnh_delta_3h_hpa"] = None

    # visibility (latest, km)
    if sub.height > 0 and "vsby" in sub.columns:
        last_vis = sub.select("vsby").drop_nulls()
        feats["vis_km"] = (
            float(last_vis["vsby"][-1]) * 1.60934
            if last_vis.height > 0
            else None
        )
    else:
        feats["vis_km"] = None

    # ceiling (latest, metres) - skyc1/skyl1 pattern
    if sub.height > 0 and "skyl1" in sub.columns:
        last_ceil = sub.select("skyl1").drop_nulls()
        feats["ceiling_m"] = (
            float(last_ceil["skyl1"][-1]) * 0.3048
            if last_ceil.height > 0
            else None
        )
    else:
        feats["ceiling_m"] = None

    # wx flags (clearing proxy: was raining in last 3h but not in last obs)
    wx_rain = False
    wx_clearing = False
    if sub.height > 0 and "wxcodes" in sub.columns:
        recent_wx = sub.filter(pl.col("ts_utc") >= cutoff_3h).select("wxcodes")
        wx_texts = [
            str(v) for v in recent_wx["wxcodes"].to_list()
            if v is not None and str(v).strip() != ""
        ]
        had_rain = any("RA" in w or "DZ" in w or "SH" in w for w in wx_texts)
        last_wx_row = sub.select("wxcodes")[-1]
        last_wx = str(last_wx_row["wxcodes"][0]) if last_wx_row.height > 0 else ""
        last_has_rain = "RA" in last_wx or "DZ" in last_wx or "SH" in last_wx
        wx_rain = had_rain
        wx_clearing = had_rain and not last_has_rain
    feats["wx_clearing_flag"] = int(wx_clearing)
    feats["wx_rain_flag"] = int(wx_rain)

    # precip 3h (p01i column, accumulated)
    if sub.height > 0 and "p01i" in sub.columns:
        recent_precip = sub.filter(pl.col("ts_utc") >= cutoff_3h).select("p01i").drop_nulls()
        if recent_precip.height > 0:
            feats["precip_3h_mm"] = float(recent_precip["p01i"].sum()) * 25.4
        else:
            feats["precip_3h_mm"] = 0.0
    else:
        feats["precip_3h_mm"] = 0.0

    # dewpoint - temperature difference (humidity proxy)
    if sub.height > 0 and "dwpf" in sub.columns and "tmpf" in sub.columns:
        last_row = sub.select(["tmpf", "dwpf"]).drop_nulls()
        if last_row.height > 0:
            tmp_c = (float(last_row["tmpf"][-1]) - 32.0) * 5.0 / 9.0
            dwp_c = (float(last_row["dwpf"][-1]) - 32.0) * 5.0 / 9.0
            feats["dwp_tmp_diff_c"] = dwp_c - tmp_c
        else:
            feats["dwp_tmp_diff_c"] = None
    else:
        feats["dwp_tmp_diff_c"] = None

    # Optional / future (None placeholders)
    feats["nwp_disagreement_score"] = None
    feats["regime_id"] = None

    return feats


__all__ = ["SPIKE_FEATURE_COLUMNS", "build_spike_features"]
