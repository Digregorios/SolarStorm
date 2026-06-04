"""Forecast metrics: MAE, RMSE, CRPS, RPS, Brier, bracket-match, corr, skill-score."""
from __future__ import annotations

import numpy as np


def mae(pred: np.ndarray, truth: np.ndarray) -> float:
    mask = ~(np.isnan(pred) | np.isnan(truth))
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs(pred[mask] - truth[mask])))


def rmse(pred: np.ndarray, truth: np.ndarray) -> float:
    mask = ~(np.isnan(pred) | np.isnan(truth))
    if mask.sum() == 0:
        return float("nan")
    return float(np.sqrt(np.mean((pred[mask] - truth[mask]) ** 2)))


def bias(pred: np.ndarray, truth: np.ndarray) -> float:
    mask = ~(np.isnan(pred) | np.isnan(truth))
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(pred[mask] - truth[mask]))


def corr(a: np.ndarray, b: np.ndarray) -> float:
    mask = ~(np.isnan(a) | np.isnan(b))
    if mask.sum() < 3:
        return float("nan")
    return float(np.corrcoef(a[mask], b[mask])[0, 1])


def skill_score(pred: np.ndarray, baseline: np.ndarray, truth: np.ndarray) -> float:
    mse_pred = np.mean((pred - truth) ** 2)
    mse_base = np.mean((baseline - truth) ** 2)
    if mse_base == 0:
        return 0.0
    return float(1.0 - mse_pred / mse_base)


def bracket_match_at_p50(p50: float, truth: int) -> float:
    return 1.0 if round(p50) == round(truth) else 0.0


def rps(prob_dist: dict[int, float], truth: int) -> float:
    keys = sorted(prob_dist)
    pred_cdf = np.cumsum([prob_dist[k] for k in keys])
    obs_cdf = np.array([1.0 if k >= truth else 0.0 for k in keys])
    return float(np.mean((pred_cdf - obs_cdf) ** 2))


def crps_ensemble(ensemble: np.ndarray, truth: float) -> float:
    """Continuous Ranked Probability Score for an ensemble of point predictions."""
    n = len(ensemble)
    e1 = np.mean(np.abs(ensemble - truth))
    e2 = 0.0
    for i in range(n):
        for j in range(n):
            e2 += np.abs(ensemble[i] - ensemble[j])
    e2 /= (2 * n * n)
    return float(e1 - e2)
