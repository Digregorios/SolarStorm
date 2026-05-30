"""Phase 4 walk-forward evaluation (T-4-2 .. T-4-5).

Compares per CP-operational across 3 splits:
  - persistence (k_cp)
  - climatology (Q(climo))
  - Ridge band-aware (Phase 3 baseline)
  - NWP raw (Q(nwp_t2m_at_cp))
  - NWP + residual LightGBM (Phase 4 core)

Emits ``reports/phase4.md`` + ``reports/phase4.json`` with the REQ-MET-4 verdict and
the REQ-AUD-2 gate battery. corr_diff (which Phase 3 failed) is, since
criterion_version 1.1, a reported diagnostic monitor computed on anomalies - it no
longer blocks the verdict (prereg ``corr_diff.role: diagnostic_monitor``).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Iterable

import numpy as np
import polars as pl
import yaml

from audits.phases.nwp_timestamps import run_phase as run_frozen_obs_nwp
from core.baselines.climatology import (
    Climatology,
    fit_climatology,
    fit_tmax_hour_climatology,
)
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.cv import bootstrap_ci_diff, expanding_walk_forward_splits
from core.eval.gates import (
    asdict_safe,
    gate_corr_diff,
    gate_counterfactual,
    gate_coverage_ic80,
    gate_i_t_obs,
    gate_ss_vs_persistence,
    SS_1H_MIN,
    SS_3H_MIN,
)
from core.eval.metrics import bracket_match_at_p50, rps
from core.eval.permutation import permutation_importance
from core.eval.counterfactual import counterfactual_same_temp_auc
from core.eval.preregistration import (
    COMMITTED_SHA256,
    PreregistrationError,
    assert_preregistration_committed,
)
from core.features.training_panel import (
    FEATURE_COLUMNS,
    NWP_FEATURE_COLUMNS,
    build_training_panel,
)
from core.ingest.iem_csv import load_observations
from core.ingest.nwp import read_snapshots
from core.ingest.nwp_client import NCEP_GFS
from core.labels.tmax import build_tmax_labels
from core.models.loss import latent_to_prob_dist
from core.models.residual_lgbm import (
    ResidualLgbmConfig,
    fit_residual_lgbm,
    predict_int as predict_lgbm_int,
    predict_latent as predict_lgbm_latent,
)
from core.models.ridge_band import (
    RidgeBandConfig,
    fit_ridge_band,
    predict_int as predict_ridge_int,
    predict_latent as predict_ridge_latent,
)


REPO = Path(__file__).resolve().parents[1]


PHASE4_FEATURES = tuple(FEATURE_COLUMNS) + tuple(NWP_FEATURE_COLUMNS)

# Panel feature columns derived from the fitted climatology. These MUST be
# recomputed from the per-split TRAIN-ONLY (causal) climo before building X,
# otherwise a test-spanning climatology leaks into a model feature (review D1).
CLIMO_DERIVED_FEATURES: tuple[str, ...] = ("clim_tmax_c_dec",)

# Gates demoted to reported-only diagnostics (criterion_version 1.1). They are
# still computed and shown in the report but are EXCLUDED from aud2_passed.
# corr_diff: prereg ``corr_diff.role: diagnostic_monitor`` /
# ``corr_diff.blocks_verdict: false`` - its intent is absorbed by i_t_obs +
# ss(1h/3h) + counterfactual-AUC + the horizon-degradation curve.
DIAGNOSTIC_ONLY_GATES: frozenset[str] = frozenset({"corr_diff"})


def collect_gate_violations(split_results: list[dict]) -> list[tuple]:
    """Return (split, gate) pairs for blocking gates that failed.

    Diagnostic-only gates (``DIAGNOSTIC_ONLY_GATES``) and gates with
    ``passed is None`` (skipped) never count as violations.
    """
    violations: list[tuple] = []
    for r in split_results:
        for g in r["gates"]:
            gate_id = g.get("name") or g.get("phase") or "?"
            if gate_id in DIAGNOSTIC_ONLY_GATES:
                continue
            if g["passed"] is False:
                violations.append((r["split"], gate_id))
    return violations


class CausalClimatologyError(RuntimeError):
    """Raised when a climo-derived feature is built from a climatology whose
    train window overlaps the rows it is applied to (review D1).

    The Phase-3/4 panel seeds ``clim_tmax_c_dec`` once from a broad climatology
    that spans the later test years; feeding that into a model FEATURE leaks the
    test distribution. ``_evaluate_split`` must rebuild the column from a climo
    fit on train-only rows, and this error guards against a future regression
    that forgets to (the CI test ``test_causal_climatology`` exercises it).
    """


def assert_causal_climo(climo: Climatology, applied_dates: Iterable[date]) -> None:
    """Assert ``climo``'s train window does not overlap any date it is applied to.

    A causal climatology is fit strictly on rows *before* the evaluation period.
    If any ``applied_dates`` row falls within ``[train_start, train_end]`` the
    climatology has seen its own target distribution -> raise ``CausalClimatologyError``.
    """
    train_start, train_end = climo.train_window
    overlap = [d for d in applied_dates if train_start <= d <= train_end]
    if overlap:
        raise CausalClimatologyError(
            f"climo train window [{train_start.isoformat()}, {train_end.isoformat()}] "
            f"overlaps {len(overlap)} evaluation date(s) "
            f"(e.g. {overlap[0].isoformat()}); climo-derived features would leak"
        )


def _rebuild_climo_features(panel: pl.DataFrame, climo: Climatology) -> pl.DataFrame:
    """Overwrite climo-derived FEATURE columns from ``climo`` (train-only).

    Replaces the broad-climo ``clim_tmax_c_dec`` seeded in ``build_training_panel``
    with the per-split causal value so X carries no test-spanning climatology.
    """
    dates = panel["date_local"].to_list()
    clim_dec = [float(climo.tmax_dec_for(d)) for d in dates]
    return panel.with_columns(pl.Series("clim_tmax_c_dec", clim_dec, dtype=pl.Float64))


def _arrays(panel: pl.DataFrame, columns: tuple[str, ...]):
    X = np.column_stack([panel[c].to_numpy().astype(float) for c in columns])
    y_int = panel["target_tmax_int"].to_numpy().astype(int)
    return X, y_int


def horizon_degradation_curve(
    cp_values: Iterable[str],
    y_true: np.ndarray,
    pred_obs_plus_nwp: np.ndarray,
    pred_obs_only: np.ndarray,
    cp_set: Iterable[str],
) -> list[dict]:
    """Bracket-match skill per CP - the horizon-degradation curve (design 28.6).

    Skill is reported as a function of the evaluation CP, a proxy for lead-time to the
    afternoon Tmax peak: earlier CPs sit further from the peak, the latest CP closest.
    Genuine forward skill shows a positive obs+NWP-minus-obs delta that holds HOURS
    before the peak and decays smoothly toward the latest CP; a delta that appears only
    at the CP glued to the peak is nowcasting (28.6 says this curve absorbs corr_diff's
    shape/timing intent, more strictly).

    REPORTED diagnostic only: it carries NO committed threshold in
    ``phase4_preregistration.md``, so it never enters ``aud2_passed`` or
    ``phase4_ready``. Inventing a pass/fail bar here after seeing results would be the
    exact post-hoc gaming the pre-registration forbids; the curve is shown, not gated.
    """
    cp_arr = np.asarray(list(cp_values), dtype=object)
    curve: list[dict] = []
    for cp in cp_set:
        mask = cp_arr == cp
        n = int(mask.sum())
        if n == 0:
            continue  # this CP absent from the test rows; skip (no nan rows)
        bm_full = bracket_match_at_p50(pred_obs_plus_nwp[mask], y_true[mask])
        bm_obs = bracket_match_at_p50(pred_obs_only[mask], y_true[mask])
        curve.append(
            {
                "cp": cp,
                "n": n,
                "bm_obs_only": bm_obs,
                "bm_obs_plus_nwp": bm_full,
                "nwp_delta": bm_full - bm_obs,
            }
        )
    return curve


def compute_i_t_obs(
    lgbm,
    X_phase4_test: np.ndarray,
    y_test: np.ndarray,
    nwp_anchor_test: np.ndarray,
    last_obs_idx: int,
    *,
    n_repeats: int = 5,
    seed: int = 42,
) -> float:
    """Permutation importance of the current-observation feature (REQ-AUD-2 I_T_obs).

    CRITICAL: the model is scored through its OWN anchor (``nwp_anchor_test``), because
    the LGBM was fit on ``target = truth - nwp_anchor`` and ``predict_latent`` returns
    ``anchor + residual``. Passing any other series here (e.g. climatology) audits a
    mis-anchored model and silently corrupts the anti-nowcaster verdict. The anchor is a
    required positional arg so this cannot regress to a wrong-series lambda.
    """
    truth_var = float(np.var(y_test.astype(float))) or 1.0

    def r2_score(yp: np.ndarray, yt: np.ndarray) -> float:
        mse = float(np.mean((yp - yt) ** 2))
        return 1.0 - mse / truth_var

    return permutation_importance(
        X=X_phase4_test.copy(),
        y=y_test.astype(float),
        feature_index=last_obs_idx,
        score=r2_score,
        predict=lambda Xq: predict_lgbm_latent(lgbm, Xq, nwp_anchor_test),
        n_repeats=n_repeats,
        seed=seed,
    )


def _evaluate_split(
    panel: pl.DataFrame,
    *,
    cfg_full: RidgeBandConfig,
    cfg_lgbm: ResidualLgbmConfig,
    train_start: date,
    train_end: date,
    test_start: date,
    test_end: date,
    cp_op: str,
    tmp_min: int,
    tmp_max: int,
    cp_set: list,
):
    sub_train = panel.filter(panel["cp"] == cp_op)
    train = sub_train.filter(
        (sub_train["date_local"] >= train_start) & (sub_train["date_local"] <= train_end)
    )
    # Test evaluation at the operational CP (REQ-MET-4) but we ALSO run on all CPs
    # combined for tighter paired-bootstrap CI on the gain.
    test = sub_train.filter(
        (sub_train["date_local"] >= test_start) & (sub_train["date_local"] <= test_end)
    )
    test_pooled = panel.filter(
        panel["cp"].is_in(cp_set)
        & (panel["date_local"] >= test_start) & (panel["date_local"] <= test_end)
    )
    # Keep only rows with a valid NWP anchor (otherwise NWP-based models cannot run).
    # Anchor = max-of-trajectory (design 4.5.2.1); the single-hour-at-CP value remains
    # only as a feature.
    train_nwp_ok = train.filter(train["nwp_t2m_maxtraj_c"].is_not_null())
    test_nwp_ok = test.filter(test["nwp_t2m_maxtraj_c"].is_not_null())
    test_pooled_ok = test_pooled.filter(test_pooled["nwp_t2m_maxtraj_c"].is_not_null())
    if train_nwp_ok.height < 100 or test_nwp_ok.height < 30:
        raise RuntimeError(
            f"Not enough rows with NWP anchor: train={train_nwp_ok.height} "
            f"test={test_nwp_ok.height}"
        )

    # Re-fit climatology on train only
    train_labels = (
        train.select(["date_local", "target_tmax_int"])
        .rename({"target_tmax_int": "tmax_int"})
        .with_columns(pl.lit(True).alias("day_complete"))
    )
    climo = fit_climatology(train_labels, train_start=train_start, train_end=train_end)
    clim_train = np.array([float(climo.tmax_dec_for(d)) for d in train_nwp_ok["date_local"].to_list()])
    clim_test = np.array([float(climo.tmax_dec_for(d)) for d in test_nwp_ok["date_local"].to_list()])
    clim_test_pooled = np.array(
        [float(climo.tmax_dec_for(d)) for d in test_pooled_ok["date_local"].to_list()]
    )

    # Causal-climatology guard (review D1): the panel seeds clim_tmax_c_dec from a
    # broad climo spanning the test years. Rebuild that FEATURE from the train-only
    # climo for every frame, and assert the test frames do not overlap the climo's
    # train window (train rows legitimately do - the climo is fit on them).
    assert_causal_climo(climo, test_nwp_ok["date_local"].to_list())
    assert_causal_climo(climo, test_pooled_ok["date_local"].to_list())
    train_nwp_ok = _rebuild_climo_features(train_nwp_ok, climo)
    test_nwp_ok = _rebuild_climo_features(test_nwp_ok, climo)
    test_pooled_ok = _rebuild_climo_features(test_pooled_ok, climo)

    X_full_train, y_train = _arrays(train_nwp_ok, tuple(FEATURE_COLUMNS))
    X_full_test, y_test = _arrays(test_nwp_ok, tuple(FEATURE_COLUMNS))
    X_full_pool, y_pool = _arrays(test_pooled_ok, tuple(FEATURE_COLUMNS))
    X_phase4_train, _ = _arrays(train_nwp_ok, PHASE4_FEATURES)
    X_phase4_test, _ = _arrays(test_nwp_ok, PHASE4_FEATURES)
    X_phase4_pool, _ = _arrays(test_pooled_ok, PHASE4_FEATURES)
    nwp_anchor_train = train_nwp_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    nwp_anchor_test = test_nwp_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)
    nwp_anchor_pool = test_pooled_ok["nwp_t2m_maxtraj_c"].to_numpy().astype(float)

    # Ridge baseline (Phase 3) - operational CP only
    ridge = fit_ridge_band(X_full_train, y_train, config=cfg_full, clim_train=clim_train)
    ridge_pred_latent = predict_ridge_latent(ridge, X_full_test, clim=clim_test)
    ridge_pred_int = np.array([Q(float(v)) for v in ridge_pred_latent], dtype=int)
    ridge_pred_int_pool = np.array(
        [Q(float(v)) for v in predict_ridge_latent(ridge, X_full_pool, clim=clim_test_pooled)],
        dtype=int,
    )

    # NWP raw (Q(NWP_anchor))
    nwp_raw_int = np.array([Q(float(v)) for v in nwp_anchor_test], dtype=int)

    # NWP + residual LGBM: anchor = NWP_at_cp (proven better in v1 ablation).
    lgbm = fit_residual_lgbm(
        X_phase4_train, y_train, nwp_anchor_train, config=cfg_lgbm
    )
    lgbm_pred_latent = predict_lgbm_latent(lgbm, X_phase4_test, nwp_anchor_test)
    lgbm_pred_int = np.array([Q(float(v)) for v in lgbm_pred_latent], dtype=int)
    lgbm_pred_int_pool = np.array(
        [Q(float(v)) for v in predict_lgbm_latent(lgbm, X_phase4_pool, nwp_anchor_pool)],
        dtype=int,
    )

    # Paired-ablation control arm (C2, prereg acceptance.kind=paired_ablation):
    # SAME model class (residual LGBM) on OBS-ONLY features, anchored on the causal
    # climatology instead of NWP. The obs+NWP arm above adds both the NWP features
    # and the NWP anchor; the per-row delta between the two isolates the marginal
    # NWP contribution at a fixed model class (the honest attribution the reviewer
    # required, replacing max-over-heterogeneous-baselines).
    cfg_lgbm_obs = replace(cfg_lgbm, feature_columns=tuple(FEATURE_COLUMNS))
    lgbm_obs = fit_residual_lgbm(X_full_train, y_train, clim_train, config=cfg_lgbm_obs)
    lgbm_obs_pred_int = np.array(
        [Q(float(v)) for v in predict_lgbm_latent(lgbm_obs, X_full_test, clim_test)],
        dtype=int,
    )
    lgbm_obs_pred_int_pool = np.array(
        [Q(float(v)) for v in predict_lgbm_latent(lgbm_obs, X_full_pool, clim_test_pooled)],
        dtype=int,
    )

    persistence_int = test_nwp_ok["k_cp"].to_numpy().astype(int)
    clim_int = np.array([Q(float(v)) for v in clim_test], dtype=int)
    last_obs = test_nwp_ok["last_obs_tmp_c_int"].to_numpy()
    t_now_int = np.array(
        [Q(float(v)) if v is not None and not np.isnan(float(v)) else int(persistence_int[i])
         for i, v in enumerate(last_obs)],
        dtype=int,
    )

    # Bracket-match
    bm_pers = bracket_match_at_p50(persistence_int, y_test)
    bm_clim = bracket_match_at_p50(clim_int, y_test)
    bm_ridge = bracket_match_at_p50(ridge_pred_int, y_test)
    bm_nwp_raw = bracket_match_at_p50(nwp_raw_int, y_test)
    bm_lgbm = bracket_match_at_p50(lgbm_pred_int, y_test)

    bm_baseline_max = max(bm_pers, bm_clim, bm_ridge)
    if bm_pers >= bm_clim and bm_pers >= bm_ridge:
        baseline_correct = (persistence_int == y_test).astype(float)
    elif bm_clim >= bm_ridge:
        baseline_correct = (clim_int == y_test).astype(float)
    else:
        baseline_correct = (ridge_pred_int == y_test).astype(float)
    lgbm_correct = (lgbm_pred_int == y_test).astype(float)
    bm_diff_p, bm_diff_lo, bm_diff_hi = bootstrap_ci_diff(
        lgbm_correct, baseline_correct, n_bootstrap=1000, seed=42
    )

    # Pooled (all CPs in test) - same baseline rule, tighter CI.
    persistence_pool = test_pooled_ok["k_cp"].to_numpy().astype(int)
    clim_pool_int = np.array([Q(float(v)) for v in clim_test_pooled], dtype=int)
    bm_lgbm_pool = bracket_match_at_p50(lgbm_pred_int_pool, y_pool)
    bm_pers_pool = bracket_match_at_p50(persistence_pool, y_pool)
    bm_clim_pool = bracket_match_at_p50(clim_pool_int, y_pool)
    bm_ridge_pool = bracket_match_at_p50(ridge_pred_int_pool, y_pool)
    if bm_pers_pool >= bm_clim_pool and bm_pers_pool >= bm_ridge_pool:
        baseline_pool_correct = (persistence_pool == y_pool).astype(float)
    elif bm_clim_pool >= bm_ridge_pool:
        baseline_pool_correct = (clim_pool_int == y_pool).astype(float)
    else:
        baseline_pool_correct = (ridge_pred_int_pool == y_pool).astype(float)
    lgbm_pool_correct = (lgbm_pred_int_pool == y_pool).astype(float)
    bm_diff_pool_p, bm_diff_pool_lo, bm_diff_pool_hi = bootstrap_ci_diff(
        lgbm_pool_correct, baseline_pool_correct, n_bootstrap=1000, seed=42
    )

    # --- PAIRED ABLATION (C2, prereg acceptance) ---
    # primary:   LGBM(obs+NWP) - LGBM(obs-only)   -> isolates the NWP contribution
    # secondary: LGBM(obs+NWP) - Ridge(obs, Phase3) -> beats the shipped baseline
    # Same test rows, paired bootstrap; acceptance.require = ci95_low > 0 AND point > 0.
    bm_lgbm_obs = bracket_match_at_p50(lgbm_obs_pred_int, y_test)
    lgbm_obs_correct = (lgbm_obs_pred_int == y_test).astype(float)
    abl_primary_p, abl_primary_lo, abl_primary_hi = bootstrap_ci_diff(
        lgbm_correct, lgbm_obs_correct, n_bootstrap=1000, seed=42
    )
    ridge_correct = (ridge_pred_int == y_test).astype(float)
    abl_secondary_p, abl_secondary_lo, abl_secondary_hi = bootstrap_ci_diff(
        lgbm_correct, ridge_correct, n_bootstrap=1000, seed=42
    )
    # Pooled (tighter CI, same model class).
    bm_lgbm_obs_pool = bracket_match_at_p50(lgbm_obs_pred_int_pool, y_pool)
    lgbm_obs_pool_correct = (lgbm_obs_pred_int_pool == y_pool).astype(float)
    abl_primary_pool_p, abl_primary_pool_lo, abl_primary_pool_hi = bootstrap_ci_diff(
        lgbm_pool_correct, lgbm_obs_pool_correct, n_bootstrap=1000, seed=42
    )

    # Horizon-degradation curve (design 28.6): bracket-match by CP (lead-to-peak
    # proxy), obs-only vs obs+NWP, on the pooled all-CP test rows (aligned row-for-row
    # with lgbm_*_pred_int_pool). Reported diagnostic, never a gate.
    horizon = horizon_degradation_curve(
        test_pooled_ok["cp"].to_list(), y_pool,
        lgbm_pred_int_pool, lgbm_obs_pred_int_pool, cp_set,
    )

    # RPS for NWP+residual
    prob_dists_lgbm = []
    for v, d in zip(lgbm_pred_latent, test_nwp_ok["date_local"].to_list(), strict=True):
        p10, p90 = climo.percentiles_for(d)
        sk = support_K(p10, p90, tmp_min=tmp_min, tmp_max=tmp_max)
        prob_dists_lgbm.append(
            latent_to_prob_dist(float(v), sk, tau=cfg_lgbm.tau, mode=cfg_lgbm.mode)
        )
    rps_lgbm = float(np.mean([rps(p, t) for p, t in zip(prob_dists_lgbm, y_test)]))

    # IC80 sanity (Phase 5 will calibrate)
    ic_low = lgbm_pred_int - 1
    ic_high = lgbm_pred_int + 1

    # Gates (REQ-AUD-2)
    g_ss1 = gate_ss_vs_persistence(
        lgbm_pred_int, persistence_int, y_test, label="ss_1h", threshold=SS_1H_MIN,
    )
    g_ss3 = gate_ss_vs_persistence(
        lgbm_pred_int, persistence_int, y_test, label="ss_3h_proxy", threshold=SS_3H_MIN,
    )
    # corr_diff DEMOTED to diagnostic monitor (criterion_version 1.1; prereg
    # corr_diff.role=diagnostic_monitor, blocks_verdict=false). Computed on
    # ANOMALIES vs the causal per-split climo - the SAME base for pred/truth/t_now -
    # so it measures skill beyond climatology rather than re-rewarding the seasonal
    # cycle. REPORTED but excluded from aud2_passed (see the violation loop in main).
    clim_anom_base = clim_test
    g_corr = gate_corr_diff(
        lgbm_pred_latent - clim_anom_base,
        y_test.astype(float) - clim_anom_base,
        t_now_int.astype(float) - clim_anom_base,
    )
    g_cov = gate_coverage_ic80(
        y_test, ic_low, ic_high,
        skip_reason="phase4_uses_naive_ic_p50_pm_1; conformal_in_phase5",
    )
    last_obs_idx = PHASE4_FEATURES.index("last_obs_tmp_c_int")
    imp_t_now = compute_i_t_obs(lgbm, X_phase4_test, y_test, nwp_anchor_test, last_obs_idx)
    g_i = gate_i_t_obs(imp_t_now)

    auc, n_pairs = counterfactual_same_temp_auc(
        k_cp=persistence_int,
        month=np.array([d.month for d in test_nwp_ok["date_local"].to_list()]),
        pred_latent=lgbm_pred_latent,
    )
    g_cf = gate_counterfactual(auc)

    # NWP frozen-observation extension (reforco B)
    nwp_runs = test_nwp_ok.select(["cp_utc", "nwp_run_time_utc"]).drop_nulls()
    selections_for_audit = [
        {"cp_utc": r["cp_utc"], "run_time_utc": r["nwp_run_time_utc"], "model": "ensemble"}
        for r in nwp_runs.iter_rows(named=True)
    ]
    g_nwp_ts = run_frozen_obs_nwp(nwp_selections=selections_for_audit)

    return {
        "train_window": [train_start.isoformat(), train_end.isoformat()],
        "test_window": [test_start.isoformat(), test_end.isoformat()],
        "n_train": int(train_nwp_ok.height),
        "n_test": int(test_nwp_ok.height),
        "alpha_ridge": float(ridge.alpha),
        "lgbm_best_iter": int(lgbm.best_iteration),
        "bracket_match": {
            "persistence": bm_pers,
            "climatology": bm_clim,
            "ridge_full": bm_ridge,
            "nwp_raw": bm_nwp_raw,
            "nwp_residual_lgbm": bm_lgbm,
            "baseline_max": bm_baseline_max,
            "lgbm_minus_baseline": {
                "point": bm_diff_p,
                "ci95_low": bm_diff_lo,
                "ci95_high": bm_diff_hi,
            },
            "pooled_all_cps": {
                "n_test": int(test_pooled_ok.height),
                "lgbm": bm_lgbm_pool,
                "ridge": bm_ridge_pool,
                "persistence": bm_pers_pool,
                "climatology": bm_clim_pool,
                "lgbm_minus_baseline": {
                    "point": bm_diff_pool_p,
                    "ci95_low": bm_diff_pool_lo,
                    "ci95_high": bm_diff_pool_hi,
                },
            },
        },
        "paired_ablation": {
            "metric": "bracket_match_at_p50",
            "bm_lgbm_obs_plus_nwp": bm_lgbm,
            "bm_lgbm_obs_only": bm_lgbm_obs,
            "bm_ridge_obs_phase3": bm_ridge,
            "primary_nwp_minus_obs": {
                "point": abl_primary_p,
                "ci95_low": abl_primary_lo,
                "ci95_high": abl_primary_hi,
            },
            "secondary_nwp_minus_phase3_ridge": {
                "point": abl_secondary_p,
                "ci95_low": abl_secondary_lo,
                "ci95_high": abl_secondary_hi,
            },
            "pooled_all_cps": {
                "bm_lgbm_obs_plus_nwp": bm_lgbm_pool,
                "bm_lgbm_obs_only": bm_lgbm_obs_pool,
                "primary_nwp_minus_obs": {
                    "point": abl_primary_pool_p,
                    "ci95_low": abl_primary_pool_lo,
                    "ci95_high": abl_primary_pool_hi,
                },
            },
        },
        "horizon_degradation": horizon,
        "rps_nwp_residual": rps_lgbm,
        "gates": [asdict_safe(g_ss1), asdict_safe(g_ss3), asdict_safe(g_corr),
                  asdict_safe(g_cov), asdict_safe(g_i), asdict_safe(g_cf), g_nwp_ts],
        "counterfactual_n_pairs": n_pairs,
    }


def main() -> int:
    # Pre-registration with teeth (C3): refuse to run under a drifted contract.
    try:
        prereg_hash = assert_preregistration_committed()
    except PreregistrationError as exc:
        print("[FATAL] pre-registration check failed:")
        print(str(exc))
        return 2
    print(f"[prereg] phase4_preregistration.md OK (sha256={prereg_hash[:12]}...)")

    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        mcfg = yaml.safe_load(fh)
    tau = float(mcfg["prob_dist"]["tau"])
    mode = str(mcfg["prob_dist"]["mode"])

    print("[1/5] Loading observations + labels ...")
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)

    print("[2/5] Climatology fit (broad span; per-split refit inside) ...")
    climo = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))

    print("[3/5] Loading NWP snapshots (GFS s3_grib, causal anchor) ...")
    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    nwp_snaps = read_snapshots(
        station=cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root
    )
    print(f"  nwp_rows={nwp_snaps.height} unique_models={nwp_snaps['model'].n_unique()}")

    # Tmax-hour climatology for the max-of-trajectory window (design 4.5.2.1). Fit on
    # pre-test history (2020-2022) so the forward window is causal for ALL splits.
    thc = fit_tmax_hour_climatology(
        labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name=cfg.tz
    )

    print("[4/5] Building Phase 4 training panel ...")
    panel = build_training_panel(
        obs, labels, climo=climo, tz_name=cfg.tz, cp_set=cfg.cp_set_utc,
        nwp_snapshots=nwp_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc,
    )
    print(f"  panel_rows={panel.height}")

    cp_op = cfg.cp_operational_utc
    splits = expanding_walk_forward_splits(
        history_start=date(2020, 1, 1),
        test_starts=[date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)],
        test_length_days=365,
    )

    cfg_ridge = RidgeBandConfig(
        feature_columns=tuple(FEATURE_COLUMNS),
        alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
        tau=tau, mode=mode,
        use_climatology_anchor=True,
    )
    cfg_lgbm = ResidualLgbmConfig(
        feature_columns=PHASE4_FEATURES,
        n_estimators=500,
        learning_rate=0.05,
        num_leaves=31,
        min_data_in_leaf=20,
        tau=tau,
        mode=mode,
    )

    print(f"[5/5] Walk-forward {len(splits)} splits at CP={cp_op} ...")
    split_results = []
    for s in splits:
        print(f"  {s.name}")
        res = _evaluate_split(
            panel, cfg_full=cfg_ridge, cfg_lgbm=cfg_lgbm,
            train_start=s.train_start, train_end=s.train_end,
            test_start=s.test_start, test_end=s.test_end,
            cp_op=cp_op,
            tmp_min=cfg.tmp_c_int_plausibility.min,
            tmp_max=cfg.tmp_c_int_plausibility.max,
            cp_set=cfg.cp_set_utc,
        )
        split_results.append({"split": s.name, **res})

    # --- ACCEPTANCE = PAIRED ABLATION (C2, prereg acceptance.kind=paired_ablation) ---
    # primary delta = LGBM(obs+NWP) - LGBM(obs-only); acceptance.require =
    # ci95_low > 0 AND point > 0, in >= 2 of the ELIGIBLE splits. Split-1 (2023)
    # stays eligible until Task 7's real GFS-2023 probe proves a symmetric 2-model
    # causal ensemble impossible (prereg split1.drop_only_if); the >=2/2 fallback is
    # applied downstream only if that drop is recorded. The pooled all-CPs delta
    # (same model class, tighter CI) is an alternative route to the same per-split pass.
    def _delta_passes(d: dict) -> bool:
        return d["point"] > 0 and d["ci95_low"] > 0

    n_accept = 0
    n_accept_pooled = 0
    for r in split_results:
        if _delta_passes(r["paired_ablation"]["primary_nwp_minus_obs"]):
            n_accept += 1
        if _delta_passes(r["paired_ablation"]["pooled_all_cps"]["primary_nwp_minus_obs"]):
            n_accept_pooled += 1
    n_eligible = len(split_results)
    required = max(2, n_eligible - 1)  # >=2/3 ; becomes >=2/2 if split-1 is dropped
    acceptance_met = (n_accept >= required) or (n_accept_pooled >= required)

    # corr_diff is a diagnostic monitor (criterion_version 1.1), NOT a gate: it is
    # reported but excluded by collect_gate_violations so it cannot block
    # aud2_passed. Its intent is absorbed by i_t_obs + ss(1h/3h) +
    # counterfactual-AUC + the horizon curve.
    gates_violations = collect_gate_violations(split_results)
    aud2_passed = len(gates_violations) == 0

    out = {
        "phase": 4,
        "criterion_version": "1.1",
        "preregistration_sha256": prereg_hash,
        "cp_operational": cp_op,
        "splits": split_results,
        "acceptance_paired_ablation": {
            "kind": "paired_ablation",
            "primary": "LGBM(obs+NWP) - LGBM(obs-only)",
            "secondary": "LGBM(obs+NWP) - Ridge(obs, Phase3)",
            "metric": "bracket_match_at_p50",
            "require": "ci95_low > 0 AND point > 0",
            "n_eligible_splits": n_eligible,
            "n_required": required,
            "n_splits_passed_per_cp": n_accept,
            "n_splits_passed_pooled": n_accept_pooled,
            "passed": acceptance_met,
        },
        "aud2_gates_REQ_AUD_2": {
            "n_violations": len(gates_violations),
            "violations": [{"split": s, "gate": g} for s, g in gates_violations],
            "diagnostic_only_excluded": sorted(DIAGNOSTIC_ONLY_GATES),
            "passed": aud2_passed,
        },
        "phase4_ready": acceptance_met and aud2_passed,
    }

    out_dir = REPO / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase4.json").write_text(
        json.dumps(out, default=str, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="ascii",
    )
    (out_dir / "phase4.md").write_text(_render_md(out), encoding="ascii")
    # H0 verdict (always emitted, with the pre-registration hash + criterion_version).
    h0_verdict = {
        "phase": 4,
        "criterion_version": "1.1",
        "preregistration_sha256": prereg_hash,
        "committed_sha256": COMMITTED_SHA256,
        "acceptance_paired_ablation_passed": acceptance_met,
        "aud2_passed": aud2_passed,
        "phase4_ready": acceptance_met and aud2_passed,
        # design 28.6 horizon-degradation curve, recorded as evidence. gating=false:
        # no committed threshold, so it documents forward-skill shape without ever
        # flipping phase4_ready (anti-gaming: no post-hoc bar).
        "horizon_degradation": {
            "gating": False,
            "by_split": [
                {"split": r["split"], "by_cp": r.get("horizon_degradation", [])}
                for r in split_results
            ],
        },
    }
    (out_dir / "h0_verdict.json").write_text(
        json.dumps(h0_verdict, default=str, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="ascii",
    )
    print(f"\n[verdict]")
    print(f"  pre-registration sha256:   {prereg_hash[:12]}... (criterion_version 1.1)")
    print(f"  acceptance (paired ablation): {'PASS' if acceptance_met else 'FAIL'} "
          f"(per-CP {n_accept}/{n_eligible}, pooled {n_accept_pooled}/{n_eligible}, need {required})")
    print(f"  REQ-AUD-2 anti-nowcaster:  {'PASS' if aud2_passed else 'FAIL'} ({len(gates_violations)} violations)")
    print(f"  Phase 4 ready:             {acceptance_met and aud2_passed}")
    print(f"  see {out_dir / 'phase4.md'}")
    return 0 if (acceptance_met and aud2_passed) else 1


def _render_md(out: dict) -> str:
    acc = out["acceptance_paired_ablation"]
    ag = out["aud2_gates_REQ_AUD_2"]
    lines = [
        "# Phase 4 - NWP residual learning results",
        "",
        f"- CP operacional: `{out['cp_operational']}`",
        f"- Splits: {len(out['splits'])}",
        f"- **Acceptance (paired ablation, C2): {'PASS' if acc['passed'] else 'FAIL'}** "
        f"(per-CP {acc['n_splits_passed_per_cp']}/{acc['n_eligible_splits']}, "
        f"pooled {acc['n_splits_passed_pooled']}/{acc['n_eligible_splits']}, "
        f"need {acc['n_required']}); primary delta = `{acc['primary']}`",
        f"- **REQ-AUD-2 gates: {'PASS' if ag['passed'] else 'FAIL'}** "
        f"({ag['n_violations']} violations; corr_diff excluded as diagnostic)",
        f"- **Phase 4 ready: {out['phase4_ready']}**",
        "",
        "## Paired ablation - marginal NWP contribution (operational CP)",
        "",
        "_Acceptance isolates the NWP feature+anchor contribution at a FIXED model "
        "class (residual LGBM). primary = LGBM(obs+NWP) - LGBM(obs-only); "
        "require ci95_low > 0 AND point > 0._",
        "",
        "| split | LGBM obs+NWP | LGBM obs-only | primary delta [CI95] | vs Phase3 Ridge [CI95] |",
        "|-------|--------------|---------------|----------------------|------------------------|",
    ]
    for r in out["splits"]:
        ab = r["paired_ablation"]
        p = ab["primary_nwp_minus_obs"]
        s = ab["secondary_nwp_minus_phase3_ridge"]
        lines.append(
            f"| {r['split']} | {ab['bm_lgbm_obs_plus_nwp']:.4f} | {ab['bm_lgbm_obs_only']:.4f} | "
            f"{p['point']:+.4f} [{p['ci95_low']:+.4f}, {p['ci95_high']:+.4f}] | "
            f"{s['point']:+.4f} [{s['ci95_low']:+.4f}, {s['ci95_high']:+.4f}] |"
        )
    lines.extend([
        "",
        "## Bracket-match per split (operational CP only)",
        "",
        "| split | persistence | climatology | Ridge full | NWP raw | NWP+residual |",
        "|-------|-------------|-------------|------------|---------|--------------|",
    ])
    for r in out["splits"]:
        bm = r["bracket_match"]
        lines.append(
            f"| {r['split']} | {bm['persistence']:.4f} | {bm['climatology']:.4f} | "
            f"{bm['ridge_full']:.4f} | {bm['nwp_raw']:.4f} | **{bm['nwp_residual_lgbm']:.4f}** |"
        )
    lines.extend([
        "",
        "## Bracket-match pooled across all CPs (statistical power, same model)",
        "",
        "| split | n_test | persistence | climatology | Ridge full | obs-only LGBM | NWP+residual | pooled primary delta [CI95] |",
        "|-------|--------|-------------|-------------|------------|---------------|--------------|------------------------------|",
    ])
    for r in out["splits"]:
        p = r["bracket_match"]["pooled_all_cps"]
        ap = r["paired_ablation"]["pooled_all_cps"]
        d = ap["primary_nwp_minus_obs"]
        lines.append(
            f"| {r['split']} | {p['n_test']} | {p['persistence']:.4f} | {p['climatology']:.4f} | "
            f"{p['ridge']:.4f} | {ap['bm_lgbm_obs_only']:.4f} | **{p['lgbm']:.4f}** | "
            f"{d['point']:+.4f} [{d['ci95_low']:+.4f}, {d['ci95_high']:+.4f}] |"
        )
    # Training-window asymmetry note (update.txt integrity point): the GFS s3_grib
    # anchor only exists from 2021-03-22, so split-1's expanding train window carries
    # fewer NWP-anchored rows than splits 2-3. This is NOT leakage nor source
    # heterogeneity (same GFS anchor in every split) - just a smaller split-1 train.
    nwp_train = [(r["split"], r["train_window"], r.get("n_train")) for r in out["splits"]]
    lines.extend([
        "",
        "## Training-window asymmetry (split-1)",
        "",
        "_The GFS `s3_grib` causal anchor exists only from 2021-03-22, so split-1 "
        "(test 2023) trains on ~21 months of NWP-anchored rows while later splits train "
        "on more. This is a smaller split-1 training set, NOT leakage nor source "
        "heterogeneity (the same single GFS anchor feeds every split). All 3 splits "
        "still exceed `min_train_days=365`, so the >=2/3 acceptance rule is preserved "
        "(no split dropped, no pre-registration amendment, no sha256 recompute)._",
        "",
        "| split | train window | n_train (NWP-anchored rows) |",
        "|-------|--------------|------------------------------|",
    ])
    for split, tw, ntr in nwp_train:
        lines.append(f"| {split} | {tw[0]}..{tw[1]} | {ntr} |")
    lines.extend([
        "",
        "## Horizon-degradation curve (skill by CP = lead-to-peak; design 28.6)",
        "",
        "_REPORTED diagnostic, NOT a gate (no committed threshold in the "
        "pre-registration). Bracket-match by evaluation CP; earlier CP = longer lead "
        "to the afternoon Tmax peak. Genuine forward skill = a positive NWP delta that "
        "holds hours before the peak and degrades smoothly, not skill that appears only "
        "at the latest CP._",
        "",
        "| split | CP | n | obs-only | obs+NWP | NWP delta |",
        "|-------|----|---|----------|---------|-----------|",
    ])
    for r in out["splits"]:
        for c in r.get("horizon_degradation", []):
            lines.append(
                f"| {r['split']} | {c['cp']} | {c['n']} | {c['bm_obs_only']:.4f} | "
                f"{c['bm_obs_plus_nwp']:.4f} | {c['nwp_delta']:+.4f} |"
            )
    lines.extend(["", "## Anti-nowcaster gates (REQ-AUD-2)", "",
                  "_corr_diff is a **diagnostic monitor** (criterion_version 1.1): "
                  "computed on anomalies vs the causal per-split climatology and "
                  "reported, but it does NOT block the verdict._", ""])
    for r in out["splits"]:
        lines.append(f"### Split {r['split']}")
        lines.append("")
        lines.append("| gate | value | CI95 | threshold | passed |")
        lines.append("|------|-------|------|-----------|--------|")
        for g in r["gates"]:
            v = g.get("value", "-")
            v_str = f"{v:.4f}" if isinstance(v, float) else str(v)
            lo = g.get("ci_low")
            hi = g.get("ci_high")
            ci_str = (
                f"[{lo:+.4f}, {hi:+.4f}]"
                if isinstance(lo, (int, float)) and isinstance(hi, (int, float))
                else "-"
            )
            name = g.get("name") or g.get("phase")
            passed_str = f"{g['passed']} (diagnostic)" if name == "corr_diff" else f"{g['passed']}"
            lines.append(
                f"| {name} | {v_str} | {ci_str} | {g.get('threshold', '-')} | {passed_str} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
