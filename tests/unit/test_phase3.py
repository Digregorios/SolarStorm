"""Phase 3 unit tests."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from core.eval.counterfactual import auc_roc, counterfactual_same_temp_auc
from core.eval.cv import bootstrap_ci, bootstrap_ci_diff, expanding_walk_forward_splits
from core.eval.metrics import (
    bracket_match_at_coverage,
    bracket_match_at_p50,
    corr,
    rps,
    skill_score,
)
from core.eval.permutation import permutation_importance
from core.models.ridge_band import RidgeBandConfig, fit_ridge_band, predict_int


def test_walk_forward_splits_minimum_train():
    splits = expanding_walk_forward_splits(
        history_start=date(2020, 1, 1),
        test_starts=[date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)],
        test_length_days=365,
        min_train_days=365,
    )
    assert len(splits) == 3
    assert splits[0].train_start == date(2020, 1, 1)
    assert splits[0].train_end == date(2022, 12, 31)
    assert splits[0].test_end == date(2023, 12, 31)


def test_walk_forward_drops_too_short_train():
    splits = expanding_walk_forward_splits(
        history_start=date(2024, 1, 1),
        test_starts=[date(2024, 6, 1)],
        min_train_days=365,
    )
    assert splits == []


def test_bootstrap_ci_brackets_mean():
    rng = np.random.default_rng(0)
    sample = rng.normal(loc=5.0, scale=1.0, size=400)
    point, lo, hi = bootstrap_ci(sample, n_bootstrap=500, seed=1)
    assert abs(point - 5.0) < 0.2
    assert lo < point < hi


def test_bootstrap_ci_diff_signs_negative_when_b_is_larger():
    a = np.array([1.0, 1.0, 1.0])
    b = np.array([2.0, 2.0, 2.0])
    point, lo, hi = bootstrap_ci_diff(a, b, n_bootstrap=200, seed=0)
    assert point == -1.0
    assert hi <= 0.0


def test_bracket_match_at_p50():
    assert bracket_match_at_p50(np.array([1, 2, 3]), np.array([1, 2, 3])) == 1.0
    assert bracket_match_at_p50(np.array([1, 2, 4]), np.array([1, 2, 3])) == pytest.approx(2 / 3)


def test_bracket_match_at_coverage():
    pds = [{1: 0.1, 2: 0.6, 3: 0.3}, {1: 0.5, 2: 0.4, 3: 0.1}]
    truths = [2, 2]
    # Coverage 50%: first bucket needs only k=2 -> hit; second needs only k=1 -> miss.
    assert bracket_match_at_coverage(pds, truths, coverage=0.5) == 0.5


def test_skill_score_positive_when_pred_better():
    truth = np.array([10.0, 11.0, 12.0])
    base = np.array([8.0, 13.0, 14.0])
    pred = np.array([10.0, 11.5, 12.0])
    ss = skill_score(pred, base, truth)
    assert ss > 0.5


def test_corr_basic():
    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([2.0, 4.0, 6.0, 8.0])
    assert corr(a, b) == pytest.approx(1.0)


def test_rps_perfect_when_dist_is_indicator():
    pd = {1: 0.0, 2: 1.0, 3: 0.0}
    assert rps(pd, 2) == 0.0


def test_auc_roc_perfect():
    s = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([0, 0, 1, 1])
    assert auc_roc(s, y) == 1.0


def test_counterfactual_returns_nan_when_no_pairs():
    res, n = counterfactual_same_temp_auc(
        k_cp=np.array([10, 11]),
        month=np.array([1, 7]),
        pred_latent=np.array([10.0, 11.0]),
    )
    # Each k_cp has only one row -> no class diversity -> filtered out
    assert n == 0
    assert np.isnan(res), "Expected NaN when no valid pairs exist"


def test_permutation_importance_zero_for_irrelevant_feature():
    rng = np.random.default_rng(0)
    n = 200
    X = rng.normal(size=(n, 3))
    # Target only depends on column 0
    y = X[:, 0] * 1.5 + rng.normal(scale=0.1, size=n)

    # A model that uses only column 0 should be ROBUST to permuting cols 1/2.
    def predict(Xq: np.ndarray) -> np.ndarray:
        return Xq[:, 0] * 1.5

    def neg_mse(yp: np.ndarray, yt: np.ndarray) -> float:
        return float(-np.mean((yp - yt) ** 2))

    imp_irrelevant = permutation_importance(
        X=X.copy(), y=y, feature_index=2, score=neg_mse, predict=predict, seed=1
    )
    imp_relevant = permutation_importance(
        X=X.copy(), y=y, feature_index=0, score=neg_mse, predict=predict, seed=1
    )
    assert abs(imp_irrelevant) < 0.05
    assert imp_relevant > 0.5


def _synthetic_panel(n: int = 800, seed: int = 0):
    rng = np.random.default_rng(seed)
    clim = rng.uniform(10.0, 25.0, size=n)
    k_cp = clim + rng.normal(0.0, 1.0, size=n)
    slope = rng.normal(0.0, 0.5, size=n)
    # truth depends on clim + slope (small) + noise; integer label
    truth_dec = clim + 0.4 * slope + rng.normal(0.0, 0.5, size=n)
    truth_int = np.round(truth_dec).astype(int)
    delta = truth_int.astype(float) - clim
    X = np.column_stack([k_cp, clim, slope])
    return X, truth_int, delta


def test_ridge_band_fit_and_predict_int_runs():
    X, truth, delta = _synthetic_panel()
    cfg = RidgeBandConfig(
        feature_columns=("k_cp", "clim_tmax_c_dec", "slope_3h_c_per_h"),
        alphas=(0.1, 1.0, 10.0),
        tau=0.5,
        mode="linear",
        use_climatology_anchor=True,
    )
    clim_train = X[:, 1].copy()
    model = fit_ridge_band(X, truth, config=cfg, clim_train=clim_train)
    pred_int = predict_int(model, X, clim=clim_train)
    base_int = np.round(X[:, 1]).astype(int)
    acc_pred = float(np.mean(pred_int == truth))
    acc_base = float(np.mean(base_int == truth))
    assert acc_pred >= acc_base - 0.02


def test_ridge_band_no_temperature_variant_works_without_clim():
    X, truth, _ = _synthetic_panel()
    # Use only the slope column - no climatology
    X_nt = X[:, 2:3]
    cfg_nt = RidgeBandConfig(
        feature_columns=("slope_3h_c_per_h",),
        alphas=(0.1, 1.0, 10.0),
        tau=0.5,
        mode="linear",
        use_climatology_anchor=False,
    )
    model = fit_ridge_band(X_nt, truth, config=cfg_nt)
    pred_int = predict_int(model, X_nt)
    assert pred_int.shape == truth.shape
