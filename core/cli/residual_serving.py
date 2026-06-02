"""Serve-time residual LGBM (Onda 2 Track B, behind ``forecast --serve-residuals``).

Wires the Phase-4 residual model into single-forecast serving for CP20-22 when a
CAUSAL NWP run is available, with a DETERMINISTIC Ridge fallback otherwise. The
arm mirrors ``scripts/evaluate_serving_candidate_matrix.py`` exactly (same
``PHASE4_FEATURES``, the max-of-trajectory anchor ``nwp_t2m_maxtraj_c``, and the
production ``n_estimators=500``) so eval == serving. No new causality logic: run
selection is delegated unchanged to ``select_nwp_v1`` / ``select_max_trajectory_anchor``.

``serve_residual`` returns ``(ResidualServe, None)`` on success or
``(None, fallback_reason)`` to signal the caller to fall back to Ridge. The
fallback reasons are the operational telemetry the reviewer asked for: nothing is
served "at CP" without a recorded ``valid_time_utc`` / ``valid_time_delta_h``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import polars as pl

from core.baselines.climatology import Climatology, fit_tmax_hour_climatology
from core.features.builder import CPFeatures
from core.features.nwp import (
    NwpFeatures,
    compute_nwp_features,
    select_max_trajectory_anchor,
)
from core.features.training_panel import (
    FEATURE_COLUMNS,
    NWP_FEATURE_COLUMNS,
    build_training_panel,
)
from core.ingest.nwp import read_snapshots, select_nwp_ensemble
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.models.residual_lgbm import (
    ResidualLgbmConfig,
    fit_residual_lgbm,
    predict_dist as residual_predict_dist,
)

PHASE4_FEATURES = tuple(FEATURE_COLUMNS) + tuple(NWP_FEATURE_COLUMNS)
MODEL_VERSION = "phase5-residual-lgbm-v0"
N_ESTIMATORS = 500  # production default (matches residual_lgbm + eval == serving)

# route -> (ModelSpec, endpoint) for the per-model causal snapshots.
_ROUTE_MODEL = {
    "ecmwf_residual": (ECMWF_IFS_HRES, "single_runs"),
    "gfs_residual": (NCEP_GFS, "s3_grib"),
}


@dataclass(frozen=True)
class ResidualServe:
    prob_dist: dict[int, float]
    source: str
    model_version: str
    served_model: str
    run_time_utc: str | None
    valid_time_utc: str | None
    valid_time_delta_h: float | None
    lead_h: int | None
    run_age_h: float | None


def assemble_phase4_row(
    feats: CPFeatures, climo: Climatology, d: date, nwp: NwpFeatures
) -> np.ndarray:
    """Build the (1, 20) serve-row over ``PHASE4_FEATURES``.

    Mirrors ``build_training_panel`` EXACTLY: the obs-13 derive wind_dir sin/cos
    from ``wind_dir_deg``, month sin/cos from ``d.month`` and ``clim_tmax_c_dec``
    from the causal climatology - none of which ``build_cp_features`` populates
    directly. Missing values become NaN (the residual model imputes on its train
    means, same as the panel).
    """
    f = feats.features
    wind_dir = f.get("wind_dir_deg")
    if wind_dir is None:
        wd_sin = wd_cos = None
    else:
        rad = math.radians(float(wind_dir))
        wd_sin, wd_cos = math.sin(rad), math.cos(rad)
    obs_vals: dict[str, object] = {
        "k_cp": f.get("k_cp"),
        "clim_tmax_c_dec": float(climo.tmax_dec_for(d)),
        "slope_3h_c_per_h": f.get("slope_3h_c_per_h"),
        "slope_6h_c_per_h": f.get("slope_6h_c_per_h"),
        "last_obs_tmp_c_int": f.get("last_obs_tmp_c_int"),
        "tmax_d_minus_1_int": f.get("tmax_d_minus_1_int"),
        "tmin_d_minus_1_int": f.get("tmin_d_minus_1_int"),
        "wind_dir_sin": wd_sin,
        "wind_dir_cos": wd_cos,
        "wind_speed_kt": f.get("wind_speed_kt"),
        "qnh_hpa": f.get("qnh_hpa"),
        "month_sin": math.sin(2 * math.pi * d.month / 12.0),
        "month_cos": math.cos(2 * math.pi * d.month / 12.0),
    }
    nwp_vals: dict[str, object] = {
        "nwp_t2m_at_cp_c": nwp.nwp_t2m_at_cp_c,
        "nwp_t2m_at_cp_spread_c": nwp.nwp_t2m_at_cp_spread_c,
        "nwp_disagreement_score": nwp.nwp_disagreement_score,
        "nwp_t2m_at_cp_minus_obs_c": nwp.nwp_t2m_at_cp_minus_obs_c,
        "nwp_t2m_max_pre_cp_c": nwp.nwp_t2m_max_pre_cp_c,
        "nwp_t2m_slope_pre_cp_c_per_h": nwp.nwp_t2m_slope_pre_cp_c_per_h,
        "nwp_t2m_range_pre_cp_c": nwp.nwp_t2m_range_pre_cp_c,
    }
    merged = {**obs_vals, **nwp_vals}
    row = [
        float(merged[c]) if merged[c] is not None else float("nan")
        for c in PHASE4_FEATURES
    ]
    return np.array([row], dtype=float)


def serve_residual(
    *,
    route_model: str,
    station: str,
    obs: pl.DataFrame,
    labels: pl.DataFrame,
    climo: Climatology,
    feats: CPFeatures,
    support_k: list[int],
    cp_hhmm: str,
    d: date,
    tz_name: str,
    cp_set: Iterable[str],
    train_start_d: date,
    train_end_d: date,
    nwp_root: Path,
    tau: float = 0.5,
    mode: str = "linear",
) -> tuple[ResidualServe | None, str | None]:
    """Train + serve the residual arm for one (date, CP). Falls back to Ridge by
    returning ``(None, reason)``. Causality is delegated to ``select_nwp_v1``."""
    spec_endpoint = _ROUTE_MODEL.get(route_model)
    if spec_endpoint is None:
        return None, "route_not_residual"
    spec, endpoint = spec_endpoint

    snaps = read_snapshots(station=station, model=spec, endpoint=endpoint, out_root=nwp_root)
    thc = fit_tmax_hour_climatology(
        labels, train_start=train_start_d, train_end=train_end_d, tz_name=tz_name
    )

    train_dates = [
        r for r in labels["date_local"].drop_nulls().unique().to_list()
        if r is not None and train_start_d <= r <= train_end_d
    ]
    tpanel = build_training_panel(
        obs, labels, climo=climo, tz_name=tz_name, cp_set=cp_set,
        dates=train_dates, nwp_snapshots=snaps, nwp_models=(spec.id,),
        tmax_hour_climo=thc,
    ).filter(pl.col("cp") == cp_hhmm)
    tpanel = tpanel.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    if tpanel.height < 100:
        return None, f"residual_insufficient_train_rows_{tpanel.height}"

    # Serve-row NWP features + max-trajectory anchor (causal: same run as features).
    last_obs = feats.features.get("last_obs_tmp_c_int")
    nwp_feats = compute_nwp_features(
        snaps, cp_utc=feats.cp_utc, target_valid_utc=feats.cp_utc,
        models=(spec.id,),
        last_obs_tmp_c=float(last_obs) if last_obs is not None else None,
    )
    w_start, w_end = thc.window_utc(d, feats.cp_utc)
    anchor = select_max_trajectory_anchor(
        snaps, cp_utc=feats.cp_utc, window_start_utc=w_start, window_end_utc=w_end,
        models=(spec.id,),
    )
    if anchor.nwp_t2m_maxtraj_c is None:
        return None, "no_causal_nwp_serve_row"

    cfg = ResidualLgbmConfig(
        feature_columns=PHASE4_FEATURES, n_estimators=N_ESTIMATORS,
        learning_rate=0.05, num_leaves=31, min_data_in_leaf=20, tau=tau, mode=mode,
    )
    X_tr = np.column_stack([tpanel[c].to_numpy().astype(float) for c in PHASE4_FEATURES])
    y_tr = tpanel["target_tmax_int"].to_numpy().astype(int)
    anchor_tr = tpanel["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    fitted = fit_residual_lgbm(X_tr, y_tr, anchor_tr, config=cfg)

    x_row = assemble_phase4_row(feats, climo, d, nwp_feats)
    prob_dist = residual_predict_dist(
        fitted, x_row, np.array([float(anchor.nwp_t2m_maxtraj_c)]), [support_k]
    )[0]

    # Telemetry: per-model causal selection at CP (records the nearest-lead trace, P3b).
    sel = select_nwp_ensemble(
        snaps, cp_utc=feats.cp_utc, target_valid_utc=feats.cp_utc, models=[spec.id]
    )[spec.id]
    if sel is not None:
        vt = sel.valid_time_utc
        rt = sel.run_time_utc
        valid_time_delta_h = abs((vt - feats.cp_utc).total_seconds()) / 3600.0
        run_age_h = (feats.cp_utc - rt).total_seconds() / 3600.0
        run_time_utc = rt.isoformat()
        valid_time_utc = vt.isoformat()
        lead_h = int(sel.lead_h)
    else:
        run_time_utc = valid_time_utc = None
        valid_time_delta_h = run_age_h = None
        lead_h = None

    return (
        ResidualServe(
            prob_dist=prob_dist,
            source=f"residual_lgbm_{spec.id}",
            model_version=MODEL_VERSION,
            served_model=route_model,
            run_time_utc=run_time_utc,
            valid_time_utc=valid_time_utc,
            valid_time_delta_h=valid_time_delta_h,
            lead_h=lead_h,
            run_age_h=run_age_h,
        ),
        None,
    )


__all__ = [
    "PHASE4_FEATURES",
    "MODEL_VERSION",
    "ResidualServe",
    "assemble_phase4_row",
    "serve_residual",
]
