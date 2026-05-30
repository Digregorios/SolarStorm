"""Training panel for Phase 3 Ridge.

Wraps ``build_cp_features`` to emit a feature matrix with the columns the Ridge
model consumes plus the integer label target and the decimal delta target.

Causality is enforced upstream by ``build_cp_features`` (REQ-CON-5, REQ-AUD-4).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Iterable

import polars as pl

from core.baselines.climatology import Climatology, TmaxHourClimatology
from core.features.builder import build_cp_features
from core.features.nwp import compute_nwp_features, select_max_trajectory_anchor


# Feature columns emitted (locked v0.1.1 for Phase 3).
FEATURE_COLUMNS = (
    "k_cp",
    "clim_tmax_c_dec",
    "slope_3h_c_per_h",
    "slope_6h_c_per_h",
    "last_obs_tmp_c_int",
    "tmax_d_minus_1_int",
    "tmin_d_minus_1_int",
    "wind_dir_sin",
    "wind_dir_cos",
    "wind_speed_kt",
    "qnh_hpa",
    "month_sin",
    "month_cos",
)

# Subset used by the "no-temperature" ablation (REQ-AUD-2 secao 18 v1).
# Removes anchors that essentially carry T directly.
NO_TEMPERATURE_FEATURES = (
    "slope_3h_c_per_h",
    "slope_6h_c_per_h",
    "wind_dir_sin",
    "wind_dir_cos",
    "wind_speed_kt",
    "qnh_hpa",
    "month_sin",
    "month_cos",
)

# Phase 4 NWP features added when nwp_snapshots is provided.
NWP_FEATURE_COLUMNS = (
    "nwp_t2m_at_cp_c",
    "nwp_t2m_at_cp_spread_c",
    "nwp_disagreement_score",
    "nwp_t2m_at_cp_minus_obs_c",
    "nwp_t2m_max_pre_cp_c",
    "nwp_t2m_slope_pre_cp_c_per_h",
    "nwp_t2m_range_pre_cp_c",
)


def build_training_panel(
    observations: pl.DataFrame,
    labels: pl.DataFrame,
    *,
    climo: Climatology,
    tz_name: str,
    cp_set: Iterable[str],
    dates: Iterable[date] | None = None,
    drop_incomplete: bool = True,
    nwp_snapshots: pl.DataFrame | None = None,
    nwp_models: tuple[str, ...] = ("ecmwf_ifs_hres", "ncep_gfs_global"),
    tmax_hour_climo: TmaxHourClimatology | None = None,
) -> pl.DataFrame:
    """Build the (date_local, cp) training panel with features + target.

    When ``nwp_snapshots`` is provided, also emits ``NWP_FEATURE_COLUMNS`` per
    row (CP-causal selection enforced via ``compute_nwp_features``).
    """
    cp_set = list(cp_set)
    if dates is None:
        dates = labels["date_local"].drop_nulls().unique().to_list()

    label_map: dict[date, dict[str, object]] = {}
    if labels.height:
        for row in labels.select(["date_local", "tmax_int", "day_complete"]).iter_rows(named=True):
            d = row["date_local"]
            if d is not None:
                label_map[d] = row

    use_nwp = nwp_snapshots is not None and nwp_snapshots.height > 0

    rows: list[dict[str, object]] = []
    for d in dates:
        if d is None:
            continue
        lab = label_map.get(d)
        tmax_int = lab["tmax_int"] if lab is not None else None
        day_complete = bool(lab["day_complete"]) if lab is not None else False
        if drop_incomplete and (not day_complete or tmax_int is None):
            continue
        clim_dec = float(climo.tmax_dec_for(d))
        m_sin = math.sin(2 * math.pi * d.month / 12.0)
        m_cos = math.cos(2 * math.pi * d.month / 12.0)
        for cp in cp_set:
            # build_cp_features raises RuntimeError on causality violations
            # (REQ-CON-5); we let it propagate (review-v2 #N5: removed dead
            # try/except that was a literal no-op).
            f = build_cp_features(
                observations, date_local=d, cp_hhmm=cp, tz_name=tz_name, labels=labels
            )
            wind_dir = f.features.get("wind_dir_deg")
            ws = f.features.get("wind_speed_kt")
            if wind_dir is None or ws is None:
                wd_sin = wd_cos = None
            else:
                rad = math.radians(float(wind_dir))
                wd_sin = math.sin(rad)
                wd_cos = math.cos(rad)
            row_out: dict[str, object] = {
                "date_local": d,
                "cp": cp,
                "cp_utc": f.cp_utc,
                "feature_max_ts_utc": f.feature_max_ts_utc,
                "day_complete": day_complete,
                "target_tmax_int": int(tmax_int) if tmax_int is not None else None,
                "target_delta": (
                    float(tmax_int) - clim_dec if tmax_int is not None else None
                ),
                "k_cp": f.features.get("k_cp"),
                "clim_tmax_c_dec": clim_dec,
                "slope_3h_c_per_h": f.features.get("slope_3h_c_per_h"),
                "slope_6h_c_per_h": f.features.get("slope_6h_c_per_h"),
                "last_obs_tmp_c_int": f.features.get("last_obs_tmp_c_int"),
                "tmax_d_minus_1_int": f.features.get("tmax_d_minus_1_int"),
                "tmin_d_minus_1_int": f.features.get("tmin_d_minus_1_int"),
                "wind_dir_sin": wd_sin,
                "wind_dir_cos": wd_cos,
                "wind_speed_kt": ws,
                "qnh_hpa": f.features.get("qnh_hpa"),
                "month_sin": m_sin,
                "month_cos": m_cos,
            }
            if use_nwp:
                last_obs = f.features.get("last_obs_tmp_c_int")
                nwp = compute_nwp_features(
                    nwp_snapshots,
                    cp_utc=f.cp_utc,
                    target_valid_utc=f.cp_utc,  # Phase 4 v1: causal at CP
                    models=nwp_models,
                    last_obs_tmp_c=float(last_obs) if last_obs is not None else None,
                )
                row_out["nwp_t2m_at_cp_c"] = nwp.nwp_t2m_at_cp_c
                row_out["nwp_t2m_at_cp_spread_c"] = nwp.nwp_t2m_at_cp_spread_c
                row_out["nwp_disagreement_score"] = nwp.nwp_disagreement_score
                row_out["nwp_t2m_at_cp_minus_obs_c"] = nwp.nwp_t2m_at_cp_minus_obs_c
                row_out["nwp_t2m_max_pre_cp_c"] = nwp.nwp_t2m_max_pre_cp_c
                row_out["nwp_t2m_slope_pre_cp_c_per_h"] = nwp.nwp_t2m_slope_pre_cp_c_per_h
                row_out["nwp_t2m_range_pre_cp_c"] = nwp.nwp_t2m_range_pre_cp_c
                row_out["nwp_run_time_utc"] = nwp.nwp_run_time_utc
                row_out["nwp_lead_h"] = nwp.nwp_lead_h
                # Anchor amendment v1.1 (design 4.5.2.1): max-of-trajectory over the
                # causal run's forward Tmax-hour window. The single-hour-at-CP value
                # above stays only as a feature; this is the model anchor.
                if tmax_hour_climo is not None:
                    w_start, w_end = tmax_hour_climo.window_utc(d, f.cp_utc)
                    mta = select_max_trajectory_anchor(
                        nwp_snapshots, cp_utc=f.cp_utc,
                        window_start_utc=w_start, window_end_utc=w_end,
                        models=nwp_models,
                    )
                    row_out["nwp_t2m_maxtraj_c"] = mta.nwp_t2m_maxtraj_c
                    row_out["nwp_t2m_maxtraj_spread_c"] = mta.nwp_t2m_maxtraj_spread_c
                    if mta.run_time_utc is not None:
                        row_out["nwp_run_time_utc"] = mta.run_time_utc
            rows.append(row_out)
    schema_overrides: dict[str, pl.DataType] = {
        "k_cp": pl.Int32,
        "clim_tmax_c_dec": pl.Float64,
        "slope_3h_c_per_h": pl.Float64,
        "slope_6h_c_per_h": pl.Float64,
        "last_obs_tmp_c_int": pl.Int32,
        "tmax_d_minus_1_int": pl.Int32,
        "tmin_d_minus_1_int": pl.Int32,
        "wind_dir_sin": pl.Float64,
        "wind_dir_cos": pl.Float64,
        "wind_speed_kt": pl.Float64,
        "qnh_hpa": pl.Float64,
        "month_sin": pl.Float64,
        "month_cos": pl.Float64,
        "target_tmax_int": pl.Int32,
        "target_delta": pl.Float64,
    }
    if use_nwp:
        schema_overrides.update({
            "nwp_t2m_at_cp_c": pl.Float64,
            "nwp_t2m_at_cp_spread_c": pl.Float64,
            "nwp_disagreement_score": pl.Float64,
            "nwp_t2m_at_cp_minus_obs_c": pl.Float64,
            "nwp_t2m_max_pre_cp_c": pl.Float64,
            "nwp_t2m_slope_pre_cp_c_per_h": pl.Float64,
            "nwp_t2m_range_pre_cp_c": pl.Float64,
            "nwp_run_time_utc": pl.Datetime("us", time_zone="UTC"),
            "nwp_lead_h": pl.Int32,
            "nwp_t2m_maxtraj_c": pl.Float64,
            "nwp_t2m_maxtraj_spread_c": pl.Float64,
        })
    return pl.DataFrame(rows, schema_overrides=schema_overrides, infer_schema_length=None)


__all__ = [
    "FEATURE_COLUMNS",
    "NO_TEMPERATURE_FEATURES",
    "NWP_FEATURE_COLUMNS",
    "build_training_panel",
]
