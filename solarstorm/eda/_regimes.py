"""Heuristic regime classifier — data-driven thresholds (P2).

Classifies each local day into one of: calm, transition, late_warming, foehn_nw, disrupted.
Thresholds are calibrated on NZWN EDA and documented with justification.
"""
from __future__ import annotations

import polars as pl


def classify_regime(day_obs: pl.DataFrame) -> tuple[str, dict]:
    """Classify a single day's observations into a regime.

    Expects columns: ts_local, tmp_c_int, wind_dir_deg, sknt, dwp_c_int, p01i.

    Returns (regime_label, flags_dict).
    """
    if day_obs.height < 3:
        return "calm", {}

    obs = day_obs.sort("ts_local")

    # Hourly delta
    obs = obs.with_columns(
        (pl.col("tmp_c_int").diff().cast(pl.Float64) /
         pl.col("ts_local").diff().dt.total_hours().cast(pl.Float64)).alias("delta_t_per_h")
    )

    max_delta = obs["delta_t_per_h"].max() or 0.0
    dwp_depression = (obs["tmp_c_int"] - obs["dwp_c_int"]).mean()

    # Wind direction stability
    dirs = obs["wind_dir_deg"].drop_nulls()
    wind_nw = dirs.filter((dirs >= 270) | (dirs <= 45)).len() / max(dirs.len(), 1)

    # Mean wind speed. Wellington foehn is a STRONG downslope NW flow, so wind
    # speed (not just direction + drying) is the physical discriminator. Source:
    # scripts/eda_regime_path.py:262-274 defines the foehn-like proxy as NW/W
    # wind + rising temp + drying; the strong-wind cut separates true foehn from
    # ordinary calm/late days that also happen to sit in the northerly quadrant.
    mean_sknt = obs["sknt"].mean() or 0.0

    # Precipitation
    has_precip = (obs["p01i"].sum() or 0.0) > 0.01

    # Late warming = the daily maximum occurs late in the local day (evening),
    # i.e. Tmax lands after the checkpoint. Source: core/labels/tmax.py:8
    # (late_spike_l1 := k_eod != k_cp) and reports/late_warming_bias_audit.md,
    # where the operative signal is P(tmax_hour > cp_hour). A fixed °C/h rate is
    # too brittle at the 3-hourly METAR cadence, so we key off the Tmax hour.
    tmax_idx = obs["tmp_c_int"].arg_max()
    tmax_hour = obs["ts_local"][tmax_idx].hour
    late_warming = tmax_hour >= 18

    # Check intraday regime change
    early_dir = obs.filter(pl.col("ts_local").dt.hour() <= 12)["wind_dir_deg"].mean()
    late_dir = obs.filter(pl.col("ts_local").dt.hour() >= 15)["wind_dir_deg"].mean()
    intraday_change = abs(late_dir - early_dir) > 90 if (early_dir is not None and late_dir is not None) else False

    flags = {"intraday_regime_change": intraday_change}

    # Classify
    if has_precip or max_delta < -2.0:
        regime = "disrupted"
    elif wind_nw > 0.5 and dwp_depression > 4.0 and mean_sknt > 15.0:
        regime = "foehn_nw"
    elif late_warming:
        regime = "late_warming"
    elif max_delta > 1.0:
        regime = "transition"
    else:
        regime = "calm"

    return regime, flags
