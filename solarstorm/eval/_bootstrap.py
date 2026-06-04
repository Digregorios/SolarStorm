"""Bootstrap confidence intervals for forecast evaluation."""
from __future__ import annotations

import numpy as np


def bootstrap_ci(
    values: np.ndarray,
    statistic: callable = np.mean,
    *,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    point = statistic(values)
    boot_stats = np.empty(n_bootstrap)
    n = len(values)
    for i in range(n_bootstrap):
        sample = rng.choice(values, size=n, replace=True)
        boot_stats[i] = statistic(sample)
    alpha = (1 - confidence) / 2
    lo = float(np.percentile(boot_stats, 100 * alpha))
    hi = float(np.percentile(boot_stats, 100 * (1 - alpha)))
    return point, lo, hi


def bootstrap_ci_diff(
    a: np.ndarray,
    b: np.ndarray,
    *,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Bootstrap CI for mean(a) - mean(b) with paired indices."""
    if len(a) != len(b):
        raise ValueError(f"Arrays must be same length, got {len(a)} vs {len(b)}")
    rng = np.random.default_rng(seed)
    point = float(np.mean(a) - np.mean(b))
    boot_diffs = np.empty(n_bootstrap)
    n = len(a)
    for i in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        boot_diffs[i] = np.mean(a[idx]) - np.mean(b[idx])
    alpha = (1 - confidence) / 2
    lo = float(np.percentile(boot_diffs, 100 * alpha))
    hi = float(np.percentile(boot_diffs, 100 * (1 - alpha)))
    return point, lo, hi
