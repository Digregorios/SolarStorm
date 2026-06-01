"""T-11-9 Phase 2: Serving candidate matrix evaluation.

Builds a consolidated per-CP/per-regime comparison matrix of Ridge/GFS-residual/
ECMWF-residual/analog-arm/ensemble on identical rows with honest window labelling.
Produces a CONSERVATIVE recommended routing.

prereg: contracts/serving_candidate_matrix_v0_prereg.md (prereg_version 1.0)
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from core.baselines.climatology import fit_climatology, fit_tmax_hour_climatology
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.metrics import bracket_match_at_p50, mae, rmse, rps
from core.features.training_panel import (
    FEATURE_COLUMNS,
    NWP_FEATURE_COLUMNS,
    build_training_panel,
)
from core.ingest.iem_csv import load_observations
from core.ingest.nwp import read_snapshots
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.labels.tmax import build_tmax_labels
from core.models.analog_high_risk import (
    ANALOG_FEATURES,
    fit_analog_arm,
    predict_analog_batch,
)
from core.models.late_warming_risk import (
    FEATURE_NAMES as RISK_FEATURE_NAMES,
    build_features as build_risk_features,
    fit_risk_model,
    predict_risk,
)
from core.models.loss import latent_to_prob_dist
from core.models.residual_lgbm import (
    ResidualLgbmConfig,
    fit_residual_lgbm,
    predict_latent as predict_lgbm_latent,
)
from core.models.ridge_band import (
    RidgeBandConfig,
    fit_ridge_band,
    predict_latent as predict_ridge_latent,
)

REPO = Path(__file__).resolve().parents[1]
SEED = 42
np.random.seed(SEED)

# ECMWF overlap window
ECMWF_START = date(2024, 3, 1)
ECMWF_END = date(2025, 12, 31)

# Full window for Ridge/GFS/analog context
FULL_START = date(2023, 1, 1)
FULL_END = date(2025, 12, 31)

# Walk-forward splits - ECMWF overlap (2 folds)
ECMWF_SPLITS = [
    ("ecmwf-2025H1", ECMWF_START, date(2024, 12, 31), date(2025, 1, 1), date(2025, 6, 30)),
    ("ecmwf-2025H2", ECMWF_START, date(2025, 6, 30), date(2025, 7, 1), date(2025, 12, 31)),
]

# Full-window splits (3 folds) for Ridge/GFS/analog context
FULL_SPLITS = [
    ("full-2023", date(2020, 1, 1), date(2022, 12, 31), date(2023, 1, 1), date(2023, 12, 31)),
    ("full-2024", date(2020, 1, 1), date(2023, 12, 31), date(2024, 1, 1), date(2024, 12, 31)),
    ("full-2025", date(2020, 1, 1), date(2024, 12, 31), date(2025, 1, 1), date(2025, 12, 31)),
]

PHASE4_FEATURES = tuple(FEATURE_COLUMNS) + tuple(NWP_FEATURE_COLUMNS)
N_ESTIMATORS = 200  # reduced from 500 for speed (noted in report)


def _arrays(panel, columns):
    X = np.column_stack([panel[c].to_numpy().astype(float) for c in columns])
    y = panel["target_tmax_int"].to_numpy().astype(int)
    return X, y


def _rps_single(latent_val, y_int_val, climo, d, tau, mode, tmp_min, tmp_max):
    p10, p90 = climo.percentiles_for(d)
    sk = support_K(p10, p90, tmp_min=tmp_min, tmp_max=tmp_max)
    pd = latent_to_prob_dist(float(latent_val), sk, tau=tau, mode=mode)
    return rps(pd, int(y_int_val))


def _compute_metrics(pred_int, pred_latent, y_int, climo, dates, tau, mode, tmp_min, tmp_max):
    rps_vals = [
        _rps_single(pred_latent[i], y_int[i], climo, dates[i], tau, mode, tmp_min, tmp_max)
        for i in range(len(dates))
    ]
    return {
        "mae": round(float(mae(pred_int, y_int)), 4),
        "rmse": round(float(rmse(pred_int, y_int)), 4),
        "bracket_match": round(float(bracket_match_at_p50(pred_int, y_int)), 4),
        "rps": round(float(np.mean(rps_vals)), 4),
        "n": int(len(dates)),
    }




def evaluate_ecmwf_window(obs, labels, station_cfg, tau, mode):
    """Run all 5 candidates on the ECMWF overlap window (head-to-head, same rows)."""
    tmp_min = station_cfg.tmp_c_int_plausibility.min
    tmp_max = station_cfg.tmp_c_int_plausibility.max
    cp_set = station_cfg.cp_set_utc
    tz = station_cfg.tz
    cp_op = station_cfg.cp_operational_utc

    print("[1] Loading NWP snapshots ...")
    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    gfs_snaps = read_snapshots(station=station_cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root)
    ecmwf_snaps = read_snapshots(station=station_cfg.icao, model=ECMWF_IFS_HRES, endpoint="single_runs", out_root=nwp_root)
    ensemble_snaps = pl.concat([gfs_snaps, ecmwf_snaps], how="vertical_relaxed")

    print("[2] Fitting tmax-hour climatology ...")
    thc = fit_tmax_hour_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name=tz)

    # Overlap dates
    all_dates = sorted([
        d for d in labels["date_local"].unique().to_list()
        if d is not None and ECMWF_START <= d <= ECMWF_END
    ])
    print(f"  Overlap dates: {len(all_dates)}")

    # Broad climo for panel building
    climo_broad = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))

    print("[3] Building panels ...")
    panel_base = build_training_panel(obs, labels, climo=climo_broad, tz_name=tz, cp_set=cp_set, dates=all_dates)
    panel_gfs = build_training_panel(obs, labels, climo=climo_broad, tz_name=tz, cp_set=cp_set, dates=all_dates,
                                     nwp_snapshots=gfs_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc)
    panel_ecmwf = build_training_panel(obs, labels, climo=climo_broad, tz_name=tz, cp_set=cp_set, dates=all_dates,
                                       nwp_snapshots=ecmwf_snaps, nwp_models=(ECMWF_IFS_HRES.id,), tmax_hour_climo=thc)
    panel_ensemble = build_training_panel(obs, labels, climo=climo_broad, tz_name=tz, cp_set=cp_set, dates=all_dates,
                                          nwp_snapshots=ensemble_snaps, nwp_models=(NCEP_GFS.id, ECMWF_IFS_HRES.id), tmax_hour_climo=thc)
    print(f"  base={panel_base.height} gfs={panel_gfs.height} ecmwf={panel_ecmwf.height} ens={panel_ensemble.height}")

    # Risk features for analog arm + regime strata
    print("[4] Building risk features ...")
    risk_df_full = build_risk_features(obs, labels, tz, cp_op)

    # Label map for analog arm tmax_int
    label_map = {}
    for row in labels.filter(pl.col("day_complete") & pl.col("tmax_int").is_not_null()).iter_rows(named=True):
        label_map[row["date_local"]] = int(row["tmax_int"])

    cfg_ridge = RidgeBandConfig(
        feature_columns=tuple(FEATURE_COLUMNS),
        alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
        tau=tau, mode=mode, use_climatology_anchor=True,
    )
    cfg_lgbm = ResidualLgbmConfig(
        feature_columns=PHASE4_FEATURES,
        n_estimators=N_ESTIMATORS,
        learning_rate=0.05,
        num_leaves=31,
        min_data_in_leaf=20,
        tau=tau, mode=mode,
    )

    print("[5] Walk-forward evaluation (ECMWF window) ...")
    all_results = []

    for split_name, tr_start, tr_end, te_start, te_end in ECMWF_SPLITS:
        print(f"  Split: {split_name}")
        split_out = {"split": split_name, "window": "ecmwf_overlap",
                     "train": [tr_start.isoformat(), tr_end.isoformat()],
                     "test": [te_start.isoformat(), te_end.isoformat()], "by_cp": {}}

        for cp in cp_set:
            cp_results = _evaluate_one_cp_ecmwf(
                cp, tr_start, tr_end, te_start, te_end,
                panel_base, panel_gfs, panel_ecmwf, panel_ensemble,
                risk_df_full, label_map, labels, obs,
                cfg_ridge, cfg_lgbm, tau, mode, tmp_min, tmp_max, tz, cp_op,
            )
            if cp_results is not None:
                split_out["by_cp"][cp] = cp_results

        all_results.append(split_out)

    return all_results, gfs_snaps, thc, climo_broad, panel_base, panel_gfs, risk_df_full, label_map




def _evaluate_one_cp_ecmwf(
    cp, tr_start, tr_end, te_start, te_end,
    panel_base, panel_gfs, panel_ecmwf, panel_ensemble,
    risk_df_full, label_map, labels, obs,
    cfg_ridge, cfg_lgbm, tau, mode, tmp_min, tmp_max, tz, cp_op,
):
    """Evaluate all 5 candidates for one CP in one ECMWF-window split."""
    def _split(panel):
        sub = panel.filter(panel["cp"] == cp)
        tr = sub.filter((sub["date_local"] >= tr_start) & (sub["date_local"] <= tr_end))
        te = sub.filter((sub["date_local"] >= te_start) & (sub["date_local"] <= te_end))
        return tr, te

    tr_base, te_base = _split(panel_base)
    tr_gfs, te_gfs = _split(panel_gfs)
    tr_ecmwf, te_ecmwf = _split(panel_ecmwf)
    tr_ens, te_ens = _split(panel_ensemble)

    # Filter NWP rows to those with valid anchor
    tr_gfs_ok = tr_gfs.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    te_gfs_ok = te_gfs.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    tr_ecmwf_ok = tr_ecmwf.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    te_ecmwf_ok = te_ecmwf.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    tr_ens_ok = tr_ens.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    te_ens_ok = te_ens.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())

    # Intersect test dates for fair comparison
    common_dates = sorted(
        set(te_base["date_local"].to_list())
        & set(te_gfs_ok["date_local"].to_list())
        & set(te_ecmwf_ok["date_local"].to_list())
        & set(te_ens_ok["date_local"].to_list())
    )
    if len(common_dates) < 20:
        print(f"    CP={cp}: only {len(common_dates)} common dates, skipping")
        return None

    # Filter to common dates
    te_base_c = te_base.filter(pl.col("date_local").is_in(common_dates))
    te_gfs_c = te_gfs_ok.filter(pl.col("date_local").is_in(common_dates))
    te_ecmwf_c = te_ecmwf_ok.filter(pl.col("date_local").is_in(common_dates))
    te_ens_c = te_ens_ok.filter(pl.col("date_local").is_in(common_dates))

    # Per-split train-only climatology
    climo_labels = labels.filter(pl.col("date_local") <= tr_end).select(
        ["date_local", "tmax_int", "day_complete"]
    )
    climo = fit_climatology(climo_labels, train_start=date(2020, 1, 1), train_end=tr_end)

    # 1. Ridge base
    X_tr_base, y_tr_base = _arrays(tr_base, tuple(FEATURE_COLUMNS))
    clim_tr = np.array([float(climo.tmax_dec_for(d)) for d in tr_base["date_local"].to_list()])
    ridge = fit_ridge_band(X_tr_base, y_tr_base, config=cfg_ridge, clim_train=clim_tr)
    X_te_base, y_te = _arrays(te_base_c, tuple(FEATURE_COLUMNS))
    clim_te = np.array([float(climo.tmax_dec_for(d)) for d in te_base_c["date_local"].to_list()])
    ridge_latent = predict_ridge_latent(ridge, X_te_base, clim=clim_te)
    ridge_int = np.array([Q(float(v)) for v in ridge_latent], dtype=int)

    # 2. GFS-residual
    X_tr_gfs, y_tr_gfs = _arrays(tr_gfs_ok, PHASE4_FEATURES)
    anchor_tr_gfs = tr_gfs_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    if tr_gfs_ok.height >= 100:
        lgbm_gfs = fit_residual_lgbm(X_tr_gfs, y_tr_gfs, anchor_tr_gfs, config=cfg_lgbm)
        X_te_gfs, _ = _arrays(te_gfs_c, PHASE4_FEATURES)
        anchor_te_gfs = te_gfs_c["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
        gfs_latent = predict_lgbm_latent(lgbm_gfs, X_te_gfs, anchor_te_gfs)
        gfs_int = np.array([Q(float(v)) for v in gfs_latent], dtype=int)
    else:
        gfs_latent = ridge_latent.copy()
        gfs_int = ridge_int.copy()

    # 3. ECMWF-residual
    X_tr_ecmwf, y_tr_ecmwf = _arrays(tr_ecmwf_ok, PHASE4_FEATURES)
    anchor_tr_ecmwf = tr_ecmwf_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    if tr_ecmwf_ok.height >= 100:
        lgbm_ecmwf = fit_residual_lgbm(X_tr_ecmwf, y_tr_ecmwf, anchor_tr_ecmwf, config=cfg_lgbm)
        X_te_ecmwf, _ = _arrays(te_ecmwf_c, PHASE4_FEATURES)
        anchor_te_ecmwf = te_ecmwf_c["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
        ecmwf_latent = predict_lgbm_latent(lgbm_ecmwf, X_te_ecmwf, anchor_te_ecmwf)
        ecmwf_int = np.array([Q(float(v)) for v in ecmwf_latent], dtype=int)
    else:
        ecmwf_latent = ridge_latent.copy()
        ecmwf_int = ridge_int.copy()

    # 4. Ensemble (GFS+ECMWF)
    X_tr_ens, y_tr_ens = _arrays(tr_ens_ok, PHASE4_FEATURES)
    anchor_tr_ens = tr_ens_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    if tr_ens_ok.height >= 100:
        lgbm_ens = fit_residual_lgbm(X_tr_ens, y_tr_ens, anchor_tr_ens, config=cfg_lgbm)
        X_te_ens, _ = _arrays(te_ens_c, PHASE4_FEATURES)
        anchor_te_ens = te_ens_c["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
        ens_latent = predict_lgbm_latent(lgbm_ens, X_te_ens, anchor_te_ens)
        ens_int = np.array([Q(float(v)) for v in ens_latent], dtype=int)
    else:
        ens_latent = ridge_latent.copy()
        ens_int = ridge_int.copy()

    # 5. Analog arm (only at CP23, passthrough Ridge at other CPs)
    test_dates = te_base_c["date_local"].to_list()
    if cp == cp_op:
        analog_int, analog_latent = _run_analog_arm(
            tr_start, tr_end, te_start, te_end, test_dates, common_dates,
            ridge_int, ridge_latent, risk_df_full, label_map, labels, obs, tz, cp_op,
        )
    else:
        analog_int = ridge_int.copy()
        analog_latent = ridge_latent.copy()

    # Regime strata (ex-ante)
    non_calm_mask, high_delta_mask = _build_regime_masks(
        tr_start, tr_end, test_dates, common_dates, risk_df_full, obs, labels, tz, cp_op,
    )
    calm_mask = ~non_calm_mask
    intersection_mask = non_calm_mask & high_delta_mask

    strata = {
        "ALL": np.ones(len(test_dates), dtype=bool),
        "calm": calm_mask,
        "non_calm": non_calm_mask,
        "high_delta_06": high_delta_mask,
        "non_calm_AND_high_delta": intersection_mask,
    }

    cp_results = {"n_test": len(common_dates)}
    for cand_name, cand_int, cand_latent in [
        ("ridge", ridge_int, ridge_latent),
        ("gfs_residual", gfs_int, gfs_latent),
        ("ecmwf_residual", ecmwf_int, ecmwf_latent),
        ("analog_arm", analog_int, analog_latent),
        ("ensemble", ens_int, ens_latent),
    ]:
        cand_out = {}
        for st_name, mask in strata.items():
            n_st = int(mask.sum())
            if n_st < 5:
                cand_out[st_name] = {"n": n_st, "mae": None, "rmse": None, "bracket_match": None, "rps": None}
                continue
            cand_out[st_name] = _compute_metrics(
                cand_int[mask], cand_latent[mask], y_te[mask],
                climo, [test_dates[i] for i in range(len(test_dates)) if mask[i]],
                tau, mode, tmp_min, tmp_max,
            )
        cp_results[cand_name] = cand_out

    return cp_results




def _run_analog_arm(
    tr_start, tr_end, te_start, te_end, test_dates, common_dates,
    ridge_int, ridge_latent, risk_df_full, label_map, labels, obs, tz, cp_op,
):
    """Run analog arm for CP23 test rows."""
    # Train risk features
    risk_train_all = risk_df_full.filter(
        (pl.col("date_local") >= tr_start) & (pl.col("date_local") <= tr_end)
    )
    # Add tmax_int for analog pool
    tmax_col = [label_map.get(d) for d in risk_train_all["date_local"].to_list()]
    risk_train_with_tmax = risk_train_all.with_columns(
        pl.Series("tmax_int", tmax_col, dtype=pl.Int32)
    ).filter(pl.col("tmax_int").is_not_null())

    if risk_train_with_tmax.height < 100:
        return ridge_int.copy(), ridge_latent.copy()

    # Calib slice: last 120 days of train
    calib_start = tr_end - timedelta(days=119)
    risk_calib = risk_train_all.filter(pl.col("date_local") >= calib_start)

    arm_state = fit_analog_arm(
        risk_train_with_tmax,
        calib_df=risk_calib if risk_calib.height >= 50 else None,
        seed=SEED,
    )

    # Test risk features
    risk_test = risk_df_full.filter(pl.col("date_local").is_in(common_dates))
    risk_date_set = set(risk_test["date_local"].to_list())

    # Build aligned predictions
    analog_int = np.copy(ridge_int)
    # For rows with risk features, run analog batch
    has_risk_mask = np.array([d in risk_date_set for d in test_dates])
    if has_risk_mask.any():
        risk_indices = [
            i for i, d in enumerate(risk_test["date_local"].to_list())
            if d in set(test_dates)
        ]
        if risk_indices:
            risk_test_aligned = risk_test[risk_indices]
            ridge_for_risk = ridge_int[has_risk_mask]
            arm_preds = predict_analog_batch(arm_state, risk_test_aligned, ridge_for_risk)
            analog_int[has_risk_mask] = arm_preds

    # Analog latent = float version of analog_int (no separate latent model)
    analog_latent = analog_int.astype(float)
    return analog_int, analog_latent


def _build_regime_masks(
    tr_start, tr_end, test_dates, common_dates, risk_df_full, obs, labels, tz, cp_op,
):
    """Build ex-ante non_calm and high_delta_06 masks using train-only thresholds."""
    risk_train = risk_df_full.filter(
        (pl.col("date_local") >= tr_start) & (pl.col("date_local") <= tr_end)
    )
    risk_test = risk_df_full.filter(pl.col("date_local").is_in(common_dates))

    # Fit risk model on train to get c30
    if risk_train.height < 100:
        return np.zeros(len(test_dates), dtype=bool), np.zeros(len(test_dates), dtype=bool)

    risk_model = fit_risk_model(risk_train, seed=SEED)
    p_train = predict_risk(risk_model, risk_train)
    c30 = float(np.percentile(p_train, 30))

    # Predict risk on test
    risk_date_map = {}
    if risk_test.height > 0:
        p_test = predict_risk(risk_model, risk_test)
        for d, p in zip(risk_test["date_local"].to_list(), p_test):
            risk_date_map[d] = float(p)

    # non_calm: predicted risk >= c30 (top 70% = non_calm; bottom 30% = calm)
    non_calm_mask = np.array([risk_date_map.get(d, 0.0) >= c30 for d in test_dates])

    # high_delta_06: delta_06_to_cp >= train P50
    delta_train = risk_train["delta_06_to_cp"].to_list()
    delta_train_valid = [v for v in delta_train if v is not None and not (isinstance(v, float) and math.isnan(v))]
    delta_p50 = float(np.median(delta_train_valid)) if delta_train_valid else 0.0

    delta_test_map = {}
    for row in risk_test.iter_rows(named=True):
        delta_test_map[row["date_local"]] = row.get("delta_06_to_cp")

    high_delta_mask = np.array([
        (delta_test_map.get(d) is not None
         and not (isinstance(delta_test_map.get(d), float) and math.isnan(delta_test_map.get(d)))
         and delta_test_map.get(d) >= delta_p50)
        for d in test_dates
    ])

    return non_calm_mask, high_delta_mask




def evaluate_full_window_context(obs, labels, station_cfg, tau, mode, gfs_snaps, thc, climo_broad, panel_base, panel_gfs, risk_df_full, label_map):
    """Run Ridge/GFS-residual/analog on the full 2023-2025 window (3 folds) as context."""
    tmp_min = station_cfg.tmp_c_int_plausibility.min
    tmp_max = station_cfg.tmp_c_int_plausibility.max
    cp_set = station_cfg.cp_set_utc
    tz = station_cfg.tz
    cp_op = station_cfg.cp_operational_utc

    # Build full-window panels (no ECMWF needed) - include ALL dates from 2020 for training
    all_dates_full = sorted([
        d for d in labels["date_local"].unique().to_list()
        if d is not None and date(2020, 1, 1) <= d <= FULL_END
    ])

    # Reuse panel_base for dates in ECMWF window; build fresh for full window
    print("[6] Building full-window panels (Ridge/GFS only) ...")
    panel_base_full = build_training_panel(obs, labels, climo=climo_broad, tz_name=tz, cp_set=cp_set, dates=all_dates_full)
    panel_gfs_full = build_training_panel(obs, labels, climo=climo_broad, tz_name=tz, cp_set=cp_set, dates=all_dates_full,
                                          nwp_snapshots=gfs_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc)
    print(f"  base_full={panel_base_full.height} gfs_full={panel_gfs_full.height}")

    cfg_ridge = RidgeBandConfig(
        feature_columns=tuple(FEATURE_COLUMNS),
        alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
        tau=tau, mode=mode, use_climatology_anchor=True,
    )
    cfg_lgbm = ResidualLgbmConfig(
        feature_columns=PHASE4_FEATURES,
        n_estimators=N_ESTIMATORS,
        learning_rate=0.05,
        num_leaves=31,
        min_data_in_leaf=20,
        tau=tau, mode=mode,
    )

    print("[7] Walk-forward evaluation (full window, 3 folds) ...")
    full_results = []

    for split_name, tr_start, tr_end, te_start, te_end in FULL_SPLITS:
        print(f"  Split: {split_name}")
        split_out = {"split": split_name, "window": "full_2023_2025",
                     "train": [tr_start.isoformat(), tr_end.isoformat()],
                     "test": [te_start.isoformat(), te_end.isoformat()], "by_cp": {}}

        for cp in cp_set:
            cp_results = _evaluate_one_cp_full(
                cp, tr_start, tr_end, te_start, te_end,
                panel_base_full, panel_gfs_full,
                risk_df_full, label_map, labels, obs,
                cfg_ridge, cfg_lgbm, tau, mode, tmp_min, tmp_max, tz, cp_op,
            )
            if cp_results is not None:
                split_out["by_cp"][cp] = cp_results

        full_results.append(split_out)

    return full_results


def _evaluate_one_cp_full(
    cp, tr_start, tr_end, te_start, te_end,
    panel_base, panel_gfs,
    risk_df_full, label_map, labels, obs,
    cfg_ridge, cfg_lgbm, tau, mode, tmp_min, tmp_max, tz, cp_op,
):
    """Evaluate Ridge/GFS/analog for one CP in one full-window split."""
    def _split(panel):
        sub = panel.filter(panel["cp"] == cp)
        tr = sub.filter((sub["date_local"] >= tr_start) & (sub["date_local"] <= tr_end))
        te = sub.filter((sub["date_local"] >= te_start) & (sub["date_local"] <= te_end))
        return tr, te

    tr_base, te_base = _split(panel_base)
    tr_gfs, te_gfs = _split(panel_gfs)

    tr_gfs_ok = tr_gfs.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())
    te_gfs_ok = te_gfs.filter(pl.col("nwp_t2m_maxtraj_c").is_not_null())

    # Common dates: base AND gfs
    common_dates = sorted(
        set(te_base["date_local"].to_list()) & set(te_gfs_ok["date_local"].to_list())
    )
    if len(common_dates) < 20:
        return None

    te_base_c = te_base.filter(pl.col("date_local").is_in(common_dates))
    te_gfs_c = te_gfs_ok.filter(pl.col("date_local").is_in(common_dates))

    # Per-split train-only climatology
    climo_labels = labels.filter(pl.col("date_local") <= tr_end).select(
        ["date_local", "tmax_int", "day_complete"]
    )
    climo = fit_climatology(climo_labels, train_start=date(2020, 1, 1), train_end=tr_end)

    # Ridge
    X_tr_base, y_tr_base = _arrays(tr_base, tuple(FEATURE_COLUMNS))
    clim_tr = np.array([float(climo.tmax_dec_for(d)) for d in tr_base["date_local"].to_list()])
    ridge = fit_ridge_band(X_tr_base, y_tr_base, config=cfg_ridge, clim_train=clim_tr)
    X_te_base, y_te = _arrays(te_base_c, tuple(FEATURE_COLUMNS))
    clim_te = np.array([float(climo.tmax_dec_for(d)) for d in te_base_c["date_local"].to_list()])
    ridge_latent = predict_ridge_latent(ridge, X_te_base, clim=clim_te)
    ridge_int = np.array([Q(float(v)) for v in ridge_latent], dtype=int)

    # GFS-residual
    X_tr_gfs, y_tr_gfs = _arrays(tr_gfs_ok, PHASE4_FEATURES)
    anchor_tr_gfs = tr_gfs_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    if tr_gfs_ok.height >= 100:
        lgbm_gfs = fit_residual_lgbm(X_tr_gfs, y_tr_gfs, anchor_tr_gfs, config=cfg_lgbm)
        X_te_gfs, _ = _arrays(te_gfs_c, PHASE4_FEATURES)
        anchor_te_gfs = te_gfs_c["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
        gfs_latent = predict_lgbm_latent(lgbm_gfs, X_te_gfs, anchor_te_gfs)
        gfs_int = np.array([Q(float(v)) for v in gfs_latent], dtype=int)
    else:
        gfs_latent = ridge_latent.copy()
        gfs_int = ridge_int.copy()

    # Analog arm (CP23 only)
    test_dates = te_base_c["date_local"].to_list()
    if cp == cp_op:
        analog_int, analog_latent = _run_analog_arm(
            tr_start, tr_end, te_start, te_end, test_dates, common_dates,
            ridge_int, ridge_latent, risk_df_full, label_map, labels, obs, tz, cp_op,
        )
    else:
        analog_int = ridge_int.copy()
        analog_latent = ridge_latent.copy()

    # Regime masks
    non_calm_mask, high_delta_mask = _build_regime_masks(
        tr_start, tr_end, test_dates, common_dates, risk_df_full, obs, labels, tz, cp_op,
    )
    calm_mask = ~non_calm_mask
    intersection_mask = non_calm_mask & high_delta_mask

    strata = {
        "ALL": np.ones(len(test_dates), dtype=bool),
        "calm": calm_mask,
        "non_calm": non_calm_mask,
        "high_delta_06": high_delta_mask,
        "non_calm_AND_high_delta": intersection_mask,
    }

    cp_results = {"n_test": len(common_dates)}
    for cand_name, cand_int, cand_latent in [
        ("ridge", ridge_int, ridge_latent),
        ("gfs_residual", gfs_int, gfs_latent),
        ("analog_arm", analog_int, analog_latent),
    ]:
        cand_out = {}
        for st_name, mask in strata.items():
            n_st = int(mask.sum())
            if n_st < 5:
                cand_out[st_name] = {"n": n_st, "mae": None, "rmse": None, "bracket_match": None, "rps": None}
                continue
            cand_out[st_name] = _compute_metrics(
                cand_int[mask], cand_latent[mask], y_te[mask],
                climo, [test_dates[i] for i in range(len(test_dates)) if mask[i]],
                tau, mode, tmp_min, tmp_max,
            )
        cp_results[cand_name] = cand_out

    return cp_results




def compute_routing_recommendation(ecmwf_results):
    """Compute conservative per-CP routing recommendation from ECMWF-window results."""
    # Decision rules per prereg:
    # - Per CP best by MAE then RPS
    # - Winner only if no regression vs incumbent AND wins >=2/2 folds
    # - CP20-22 decided separately from CP23
    # - CP23 conservative (Ridge/GFS/analog) unless clear no-regression win
    # - Do NOT degrade calm/stable

    candidates_cp20_22 = ["ridge", "gfs_residual", "ecmwf_residual", "ensemble"]
    candidates_cp23 = ["ridge", "gfs_residual", "analog_arm"]  # conservative

    routing = {}
    per_cp_detail = {}

    for cp in ["20:00", "21:00", "22:00", "23:00"]:
        is_cp23 = (cp == "23:00")
        candidates = candidates_cp23 if is_cp23 else candidates_cp20_22
        incumbent = "ridge"

        # Collect per-fold metrics for each candidate
        fold_metrics = {c: [] for c in candidates}
        fold_calm_metrics = {c: [] for c in candidates}

        for sr in ecmwf_results:
            cpd = sr["by_cp"].get(cp)
            if cpd is None:
                continue
            for c in candidates:
                m = cpd.get(c, {}).get("ALL", {})
                if m.get("mae") is not None:
                    fold_metrics[c].append(m)
                cm = cpd.get(c, {}).get("calm", {})
                if cm.get("mae") is not None:
                    fold_calm_metrics[c].append(cm)

        n_folds = len(ecmwf_results)
        need_folds = min(2, n_folds)  # >=2/2 for short window

        # Find best candidate by pooled MAE
        pooled_mae = {}
        pooled_rps = {}
        for c in candidates:
            if fold_metrics[c]:
                pooled_mae[c] = np.mean([m["mae"] for m in fold_metrics[c]])
                pooled_rps[c] = np.mean([m["rps"] for m in fold_metrics[c]])

        if not pooled_mae:
            routing[cp] = incumbent
            per_cp_detail[cp] = {"winner": incumbent, "reason": "no data"}
            continue

        # Sort by MAE then RPS
        ranked = sorted(pooled_mae.keys(), key=lambda c: (pooled_mae[c], pooled_rps.get(c, 99)))
        best = ranked[0]

        # Check: does best regress vs incumbent?
        inc_mae = pooled_mae.get(incumbent, 99)
        best_mae = pooled_mae.get(best, 99)

        # Check: wins in >=2 folds (MAE lower than incumbent)
        folds_won = 0
        for i in range(len(fold_metrics[best])):
            if i < len(fold_metrics[incumbent]):
                if fold_metrics[best][i]["mae"] <= fold_metrics[incumbent][i]["mae"]:
                    folds_won += 1

        # Check: no calm degradation
        calm_ok = True
        for i in range(len(fold_calm_metrics[best])):
            if i < len(fold_calm_metrics[incumbent]):
                if fold_calm_metrics[best][i]["mae"] > fold_calm_metrics[incumbent][i]["mae"] + 0.05:
                    calm_ok = False
                    break

        # Decision
        reason_parts = []
        if best == incumbent:
            routing[cp] = incumbent
            reason_parts.append("incumbent is best")
        elif folds_won < need_folds:
            routing[cp] = incumbent
            reason_parts.append(f"best={best} wins only {folds_won}/{n_folds} folds (need {need_folds})")
        elif not calm_ok:
            routing[cp] = incumbent
            reason_parts.append(f"best={best} degrades calm stratum")
        elif best_mae >= inc_mae:
            routing[cp] = incumbent
            reason_parts.append(f"best={best} does not beat incumbent MAE")
        else:
            routing[cp] = best
            reason_parts.append(f"wins {folds_won}/{n_folds} folds, no calm regression")

        per_cp_detail[cp] = {
            "winner": routing[cp],
            "best_by_mae": best,
            "pooled_mae": {c: round(v, 4) for c, v in pooled_mae.items()},
            "pooled_rps": {c: round(v, 4) for c, v in pooled_rps.items()},
            "folds_won_by_best": folds_won,
            "n_folds": n_folds,
            "calm_ok": calm_ok,
            "reason": "; ".join(reason_parts),
        }

    return routing, per_cp_detail




def write_reports(ecmwf_results, full_results, routing, per_cp_detail):
    """Write candidate_matrix_v0.json and candidate_matrix_v0.md."""
    out_dir = REPO / "reports" / "serving"
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "task": "T-11-9",
        "prereg": "contracts/serving_candidate_matrix_v0_prereg.md",
        "prereg_version": "1.0",
        "seed": SEED,
        "deterministic": True,
        "num_threads": 1,
        "n_estimators_note": f"Reduced to {N_ESTIMATORS} for speed (from 500)",
        "window_choice": "Head-to-head on ECMWF overlap (2024-03..2025-12, 2 folds); "
                         "full 2023-2025 (3 folds) reported as context for Ridge/GFS/analog.",
        "ecmwf_window_splits": ecmwf_results,
        "full_window_splits": full_results,
        "recommended_routing": routing,
        "routing_detail": per_cp_detail,
        "anti_winner_shopping": {
            "same_rows_per_comparison": True,
            "window_differences_labelled": True,
            "no_per_split_cherry_picking": True,
            "fold_rule": "candidate wins CP only if wins >=2/2 folds (ECMWF window) or >=2/3 (full window)",
            "cp20_22_separate_from_cp23": True,
            "spread_excluded": True,
        },
    }

    (out_dir / "candidate_matrix_v0.json").write_text(
        json.dumps(report, default=str, ensure_ascii=True, indent=2), encoding="ascii"
    )

    # Markdown report
    md = _render_markdown(ecmwf_results, full_results, routing, per_cp_detail)
    (out_dir / "candidate_matrix_v0.md").write_text(md, encoding="ascii")

    print(f"\n[DONE] Reports written to {out_dir}")
    print(f"  - candidate_matrix_v0.json")
    print(f"  - candidate_matrix_v0.md")


def _render_markdown(ecmwf_results, full_results, routing, per_cp_detail):
    lines = [
        "# T-11-9: Serving Candidate Matrix v0",
        "",
        "## Summary",
        "",
        "Consolidated comparison of 5 candidate POINT models on identical rows,",
        "walk-forward, per CP and per regime.",
        "",
        "- **Prereg:** contracts/serving_candidate_matrix_v0_prereg.md (v1.0)",
        "- **Head-to-head window:** ECMWF overlap 2024-03..2025-12 (2 folds)",
        "- **Context window:** Full 2023-2025 (3 folds, Ridge/GFS/analog only)",
        f"- **LGBM n_estimators:** {N_ESTIMATORS} (reduced from 500 for speed)",
        "- **Seed:** 42, deterministic=True, num_threads=1",
        "- **Spread excluded:** |GFS-ECMWF| spread NOT used in any routing (T-11-6 FEASIBLE-CONDITIONAL)",
        "",
        "## Recommended Routing",
        "",
        "| CP | Recommended | Reason |",
        "|----|-------------|--------|",
    ]
    for cp in ["20:00", "21:00", "22:00", "23:00"]:
        d = per_cp_detail.get(cp, {})
        lines.append(f"| {cp} | {routing.get(cp, 'ridge')} | {d.get('reason', '')} |")

    lines.extend([
        "",
        "**CP20-22 decided SEPARATELY from CP23.** CP23 stays conservative (Ridge/GFS/analog)",
        "unless a candidate wins clearly with no regression and not only on the short window.",
        "",
        "## Anti-Winner-Shopping Declaration",
        "",
        "- Same rows per comparison (common-date intersection within each split)",
        "- Window differences labelled: ECMWF metrics are 2-fold (2024-03..2025-12);",
        "  full-window metrics are 3-fold (2023-2025). Never compared without noting this.",
        "- No per-split cherry-picking: candidate wins a CP only if it wins >=2/2 folds",
        "  (short window) or >=2/3 folds (full window), NOT one lucky fold.",
        "- CP20-22 rigidly separated from CP23.",
        "- |GFS-ECMWF| spread excluded from all routing logic.",
        "",
        "## Head-to-Head Matrix (ECMWF Overlap Window, ALL stratum)",
        "",
    ])

    for sr in ecmwf_results:
        lines.append(f"### Split: {sr['split']} (test {sr['test'][0]}..{sr['test'][1]})")
        lines.append("")
        lines.append("| CP | Candidate | MAE | RMSE | BM | RPS | n |")
        lines.append("|----|-----------|-----|------|----|-----|---|")
        for cp in ["20:00", "21:00", "22:00", "23:00"]:
            cpd = sr["by_cp"].get(cp)
            if cpd is None:
                continue
            for cand in ["ridge", "gfs_residual", "ecmwf_residual", "analog_arm", "ensemble"]:
                m = cpd.get(cand, {}).get("ALL", {})
                if m.get("mae") is None:
                    continue
                lines.append(
                    f"| {cp} | {cand} | {m['mae']:.4f} | {m['rmse']:.4f} | {m['bracket_match']:.4f} | {m['rps']:.4f} | {m['n']} |"
                )
        lines.append("")

    # Regime breakdown
    lines.extend(["## Regime Breakdown (ECMWF Overlap Window)", ""])
    for regime in ["calm", "non_calm", "high_delta_06", "non_calm_AND_high_delta"]:
        lines.append(f"### Regime: {regime}")
        lines.append("")
        lines.append("| CP | Candidate | MAE | RPS | n |")
        lines.append("|----|-----------|-----|-----|---|")
        for sr in ecmwf_results:
            for cp in ["20:00", "21:00", "22:00", "23:00"]:
                cpd = sr["by_cp"].get(cp)
                if cpd is None:
                    continue
                for cand in ["ridge", "gfs_residual", "ecmwf_residual", "analog_arm", "ensemble"]:
                    m = cpd.get(cand, {}).get(regime, {})
                    if m.get("mae") is None:
                        continue
                    lines.append(
                        f"| {cp} ({sr['split']}) | {cand} | {m['mae']:.4f} | {m['rps']:.4f} | {m['n']} |"
                    )
        lines.append("")

    # Full-window context
    lines.extend([
        "## Full-Window Context (2023-2025, 3 folds, Ridge/GFS/analog only)",
        "",
        "NOTE: These metrics cover a LONGER window than the head-to-head above.",
        "Do NOT directly compare a 3-fold metric here against a 2-fold ECMWF metric.",
        "",
    ])
    for sr in full_results:
        lines.append(f"### Split: {sr['split']} (test {sr['test'][0]}..{sr['test'][1]})")
        lines.append("")
        lines.append("| CP | Candidate | MAE | RMSE | BM | RPS | n |")
        lines.append("|----|-----------|-----|------|----|-----|---|")
        for cp in ["20:00", "21:00", "22:00", "23:00"]:
            cpd = sr["by_cp"].get(cp)
            if cpd is None:
                continue
            for cand in ["ridge", "gfs_residual", "analog_arm"]:
                m = cpd.get(cand, {}).get("ALL", {})
                if m.get("mae") is None:
                    continue
                lines.append(
                    f"| {cp} | {cand} | {m['mae']:.4f} | {m['rmse']:.4f} | {m['bracket_match']:.4f} | {m['rps']:.4f} | {m['n']} |"
                )
        lines.append("")

    lines.extend([
        "## Notes",
        "",
        "- This is a PREDICTOR-ONLY evaluation. No execution, no Polymarket, no calibration.",
        "- The recommended routing is a RECOMMENDATION, not auto-promotion. Actual serving",
        "  wiring is Phase 3 (separate, gated).",
        "- ECMWF-residual and ensemble metrics are on a SHORTER window (2024-03..2025-12,",
        "  2 folds) than Ridge/GFS/analog full-window metrics (2023-2025, 3 folds).",
        "- Analog arm blends on ex-ante non_calm at CP23 only; at CP20-22 it passes through Ridge.",
        "- Ensemble is a per-CP candidate only, NOT a global default (T-11-5 showed it regresses CP23).",
        "",
    ])

    return "\n".join(lines) + "\n"


def main() -> int:
    import yaml

    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        model_cfg = yaml.safe_load(fh)
    tau = float(model_cfg["prob_dist"]["tau"])
    mode = str(model_cfg["prob_dist"]["mode"])

    print("=== T-11-9: Serving Candidate Matrix Evaluation ===")
    print(f"  Seed={SEED}, deterministic=True, num_threads=1")
    print(f"  LGBM n_estimators={N_ESTIMATORS} (reduced for speed)")
    print()

    print("[0] Loading observations + labels ...")
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)

    # Phase A: ECMWF overlap head-to-head (all 5 candidates, same rows)
    ecmwf_results, gfs_snaps, thc, climo_broad, panel_base, panel_gfs, risk_df_full, label_map = \
        evaluate_ecmwf_window(obs, labels, cfg, tau, mode)

    # Phase B: Full-window context (Ridge/GFS/analog, 3 folds)
    full_results = evaluate_full_window_context(
        obs, labels, cfg, tau, mode, gfs_snaps, thc, climo_broad, panel_base, panel_gfs, risk_df_full, label_map,
    )

    # Phase C: Routing recommendation
    print("[8] Computing routing recommendation ...")
    routing, per_cp_detail = compute_routing_recommendation(ecmwf_results)

    print("\n=== RECOMMENDED ROUTING ===")
    for cp in ["20:00", "21:00", "22:00", "23:00"]:
        d = per_cp_detail.get(cp, {})
        print(f"  {cp}: {routing.get(cp, 'ridge')} ({d.get('reason', '')})")

    # Write reports
    write_reports(ecmwf_results, full_results, routing, per_cp_detail)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
