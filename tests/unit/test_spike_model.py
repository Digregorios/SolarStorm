"""Unit tests for core/spike/model.py - determinism, bounds, isotonic."""

from __future__ import annotations

import numpy as np
import pytest

from core.spike.model import SpikeModelConfig, fit_spike_model, predict_spike_risk


def _make_data(n: int = 200, seed: int = 42):
    """Synthetic binary classification data."""
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, 14))
    # Label correlated with first feature
    logit = 0.5 * X[:, 0] + 0.3 * X[:, 1] + rng.standard_normal(n) * 0.5
    y = (logit > 0).astype(int)
    return X, y


class TestDeterminism:
    """REQ-MOD-6: same inputs -> same spike_risk."""

    def test_same_output_on_repeated_calls(self):
        X, y = _make_data(200, seed=42)
        cfg = SpikeModelConfig(seed=42, n_estimators=50, early_stopping_rounds=10)

        model1 = fit_spike_model(X, y, config=cfg)
        risk1 = predict_spike_risk(model1, X[:20])

        model2 = fit_spike_model(X, y, config=cfg)
        risk2 = predict_spike_risk(model2, X[:20])

        np.testing.assert_array_equal(risk1, risk2)


class TestOutputBounds:
    """spike_risk must be in [0, 1]."""

    def test_output_in_unit_interval(self):
        X, y = _make_data(200, seed=7)
        cfg = SpikeModelConfig(seed=42, n_estimators=50, early_stopping_rounds=10)
        model = fit_spike_model(X, y, config=cfg)
        risk = predict_spike_risk(model, X)
        assert np.all(risk >= 0.0)
        assert np.all(risk <= 1.0)


class TestIsotonicMonotonicity:
    """Isotonic calibration must be monotone: higher raw -> higher calibrated."""

    def test_monotone_transform(self):
        X, y = _make_data(200, seed=99)
        cfg = SpikeModelConfig(seed=42, n_estimators=50, early_stopping_rounds=10)
        model = fit_spike_model(X, y, config=cfg)

        # Generate a range of raw scores and check isotonic is non-decreasing
        raw_scores = np.linspace(0, 1, 100)
        calibrated = model.isotonic.transform(raw_scores)
        diffs = np.diff(calibrated)
        assert np.all(diffs >= -1e-10), "Isotonic regression not monotone"
