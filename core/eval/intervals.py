"""Discrete prediction interval helpers."""

from __future__ import annotations

from typing import Mapping


def discrete_ic(
    prob_dist: Mapping[int, float],
    *,
    p_low: float = 0.10,
    p_high: float = 0.90,
) -> tuple[int, int]:
    """Compute a left/right percentile interval over a discrete prob_dist.

    Sweeps ``sorted(prob_dist.keys())`` accumulating mass and reports
    ``(low, high)`` such that the cumulative mass first crosses ``p_low`` /
    ``p_high``. Defaults map to IC80.

    Uses explicit ``*_set`` booleans to avoid the sentinel bug fixed in
    review #4 (the old ``low == sorted_k[0]`` flag re-triggered on iteration 1
    whenever the first bin already crossed ``p_low``).
    """
    if not prob_dist:
        raise ValueError("prob_dist is empty")
    if not 0.0 < p_low < p_high < 1.0:
        raise ValueError(f"Invalid percentiles: low={p_low} high={p_high}")
    sorted_k = sorted(prob_dist.keys())
    cum = 0.0
    low = sorted_k[0]
    high = sorted_k[-1]
    low_set = False
    high_set = False
    for k in sorted_k:
        cum += prob_dist[k]
        if not low_set and cum >= p_low:
            low = k
            low_set = True
        if not high_set and cum >= p_high:
            high = k
            high_set = True
            break
    return low, high


__all__ = ["discrete_ic"]
