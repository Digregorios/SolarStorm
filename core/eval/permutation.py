"""Permutation importance utility (REQ-AUD-2 I_T_obs gate)."""

from __future__ import annotations

from typing import Callable

import numpy as np


def permutation_importance(
    *,
    X: np.ndarray,
    y: np.ndarray,
    feature_index: int,
    score: Callable[[np.ndarray, np.ndarray], float],
    predict: Callable[[np.ndarray], np.ndarray],
    n_repeats: int = 5,
    seed: int = 42,
) -> float:
    """Permutation importance: average drop in score when shuffling one column.

    score = lambda y_pred, y: float; higher is better. Returned value is
    (baseline_score - shuffled_score), so positive means the feature matters.
    """
    rng = np.random.default_rng(seed)
    base = score(predict(X), y)
    drops = np.empty(n_repeats, dtype=float)
    for r in range(n_repeats):
        Xp = X.copy()
        rng.shuffle(Xp[:, feature_index])
        drops[r] = base - score(predict(Xp), y)
    return float(np.mean(drops))


__all__ = ["permutation_importance"]
