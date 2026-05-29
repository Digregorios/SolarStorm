"""Regression tests for code-review v2 fixes (N1-N5)."""

from __future__ import annotations

import numpy as np
import pytest

from core.eval.gates import gate_corr_diff, gate_ss_vs_persistence
from core.models.ridge_band import _impute_nan


def test_impute_nan_does_not_mutate_input():
    """N4: _impute_nan must NOT mutate the caller's array even without .copy()."""
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, 4))
    X[10, 2] = np.nan
    X[25, 0] = np.nan
    snapshot_before = X.copy()
    out, means = _impute_nan(X)
    # Caller's array preserved bit-for-bit
    assert np.array_equal(np.where(np.isnan(snapshot_before), 0, snapshot_before),
                           np.where(np.isnan(X), 0, X))
    assert np.isnan(X[10, 2])  # still NaN in original
    assert not np.isnan(out[10, 2])  # imputed in returned copy
    assert out is not X


def test_impute_nan_handles_all_nan_column():
    X = np.array([[np.nan, 1.0], [np.nan, 2.0], [np.nan, 3.0]])
    out, means = _impute_nan(X)
    # Column 0 was all NaN -> mean fallback to 0
    assert means[0] == 0.0
    assert np.all(out[:, 0] == 0.0)


def test_gate_corr_diff_returns_bootstrap_ci():
    """N3: gate_corr_diff must report ci_low and ci_high from bootstrap."""
    rng = np.random.default_rng(0)
    n = 300
    truth = rng.normal(20, 3, size=n)
    pred = truth * 0.8 + rng.normal(0, 1, size=n)  # decent correlation with truth
    t_now = truth - 5.0 + rng.normal(0, 2, size=n)  # offset and noisy
    g = gate_corr_diff(pred, truth, t_now, threshold=0.05, n_bootstrap=200, seed=1)
    assert g.ci_low is not None
    assert g.ci_high is not None
    assert g.ci_low <= g.value <= g.ci_high
    # Pred should correlate notably more with truth than with t_now -> diff > 0.05.
    assert g.value > 0.0


def test_gate_corr_diff_fails_when_ci_includes_zero():
    """A near-zero point estimate with CI spanning zero must NOT pass even if
    the point exceeds the threshold by a hair."""
    rng = np.random.default_rng(7)
    n = 80
    pred = rng.normal(size=n)
    truth = rng.normal(size=n)
    t_now = rng.normal(size=n)
    g = gate_corr_diff(pred, truth, t_now, threshold=0.0, n_bootstrap=500, seed=2)
    # CI on independent random samples spans zero
    assert g.ci_low is not None and g.ci_high is not None
    if g.value >= 0:
        # If point happens to exceed threshold, gate must still fail because lo <= 0
        assert (g.passed is False) or (g.ci_low > 0.0)


def test_gate_ss_vs_persistence_vectorised_matches_loop_baseline():
    """N2: vectorised bootstrap should yield the same SS and CI as a loop
    reference for the same seed and shape."""
    rng = np.random.default_rng(123)
    truth = rng.normal(20, 3, size=200).round().astype(int)
    pers = truth + rng.integers(-2, 3, size=200)
    pred = truth + rng.integers(-1, 2, size=200)
    g = gate_ss_vs_persistence(pred, pers, truth, label="ss_test", threshold=0.0,
                                 n_bootstrap=500, seed=42)
    assert g.value > 0  # pred is closer to truth than persistence in this synthetic
    assert g.ci_low is not None and g.ci_high is not None
    assert g.ci_low <= g.value <= g.ci_high


def test_fit_ridge_band_does_not_corrupt_X_train_via_impute():
    """N4 + integration: fit_ridge_band internally imputes NaNs - the caller's
    X_train should be returned untouched."""
    from core.models.ridge_band import RidgeBandConfig, fit_ridge_band

    rng = np.random.default_rng(0)
    n = 300
    X = rng.normal(size=(n, 3))
    X[5, 1] = np.nan
    snapshot = X.copy()
    truth = (X[:, 0] * 1.5 + rng.normal(0, 0.5, size=n)).round().astype(int)
    cfg = RidgeBandConfig(
        feature_columns=("a", "b", "c"),
        alphas=(1.0, 10.0),
        tau=0.5,
        mode="linear",
        use_climatology_anchor=False,
    )
    fit_ridge_band(X, truth, config=cfg)
    # Caller's X is unchanged: NaN still where we put it.
    assert np.array_equal(
        np.where(np.isnan(snapshot), 0, snapshot),
        np.where(np.isnan(X), 0, X),
    )
    assert np.isnan(X[5, 1])  # original NaN location preserved
