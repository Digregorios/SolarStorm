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

    # NW-sector flow strength. Wellington foehn is a STRONG downslope NW flow, so
    # wind *intensity within the NW sector* (not just direction + drying) is the
    # physical discriminator: a 4 kt and a 22 kt northerly are meteorologically
    # different events that a direction-only test conflates. We therefore use a
    # composite — the mean wind speed of observations actually blowing from the
    # NW quadrant — rather than direction fraction alone. Source: the project's
    # own foehn-like proxy (scripts/eda_regime_path.py:262-274 — NW/W wind +
    # rising temp + drying) plus standard foehn physics (intensity is part of the
    # definition). nw_flow_strength is 0 when no obs sit in the NW sector.
    in_nw = obs.filter(
        (pl.col("wind_dir_deg") >= 270) | (pl.col("wind_dir_deg") <= 45)
    )
    nw_flow_strength = (in_nw["sknt"].mean() or 0.0) if in_nw.height > 0 else 0.0

    # foehn_score couples flow strength with dryness so neither alone fires the
    # regime. Threshold is the physical floor (>= ~15 kt strong NW flow AND a
    # >= ~4 C dewpoint depression => 15 * 4 = 60), derived from the foehn floor
    # NOT reverse-engineered from the unit fixtures.
    foehn_score = nw_flow_strength * (dwp_depression if dwp_depression is not None else 0.0)

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
    elif foehn_score > 60.0:
        regime = "foehn_nw"
    elif late_warming:
        regime = "late_warming"
    elif max_delta > 1.0:
        regime = "transition"
    else:
        regime = "calm"

    return regime, flags
