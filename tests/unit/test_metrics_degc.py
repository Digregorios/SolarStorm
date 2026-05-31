"""Unit tests for the degC point-error metrics (MAE/RMSE) added for core_predictor_status."""

from __future__ import annotations

import numpy as np
import pytest

from core.eval.metrics import mae, rmse


def test_mae_rmse_known_values():
    pred = np.array([18, 19, 20])
    truth = np.array([18, 20, 22])  # errors: 0, 1, 2
    assert mae(pred, truth) == pytest.approx(1.0)              # (0+1+2)/3
    assert rmse(pred, truth) == pytest.approx(np.sqrt(5 / 3))  # sqrt((0+1+4)/3)


def test_mae_rmse_perfect_zero():
    p = np.array([15, 16, 17])
    assert mae(p, p) == 0.0 and rmse(p, p) == 0.0


def test_mae_rmse_length_mismatch_raises():
    with pytest.raises(ValueError):
        mae(np.array([1, 2]), np.array([1]))
    with pytest.raises(ValueError):
        rmse(np.array([1, 2]), np.array([1]))


def test_rmse_ge_mae():
    rng = np.random.default_rng(0)
    p = rng.normal(18, 2, 200)
    t = p + rng.normal(0, 1.5, 200)
    assert rmse(p, t) >= mae(p, t)  # always true by Jensen
