"""Walk-forward CV utilities (REQ-MET-3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Iterable

import numpy as np


@dataclass(frozen=True)
class Split:
    name: str
    train_start: date
    train_end: date
    test_start: date
    test_end: date


def expanding_walk_forward_splits(
    *,
    history_start: date,
    test_starts: Iterable[date],
    test_length_days: int = 365,
    min_train_days: int = 365,
) -> list[Split]:
    """Build expanding-window splits.

    For each ``test_start`` in ``test_starts``:
        train = [history_start, test_start - 1d]
        test  = [test_start,    test_start + test_length_days - 1d]

    Splits with fewer than ``min_train_days`` of training are dropped.
    """
    splits: list[Split] = []
    for ts in test_starts:
        te = ts + timedelta(days=test_length_days - 1)
        tr_start = history_start
        tr_end = ts - timedelta(days=1)
        if (tr_end - tr_start).days < min_train_days:
            continue
        splits.append(
            Split(
                name=f"{ts.isoformat()}_to_{te.isoformat()}",
                train_start=tr_start,
                train_end=tr_end,
                test_start=ts,
                test_end=te,
            )
        )
    return splits


def bootstrap_ci(
    values: np.ndarray | list[float],
    *,
    statistic: Callable[[np.ndarray], float] = lambda v: float(np.mean(v)),
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Bootstrap CI of ``statistic`` over a flat sample.

    Returns ``(point, low, high)`` where bounds are the
    ``(1-confidence)/2`` and ``1-(1-confidence)/2`` percentiles.
    """
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return float("nan"), float("nan"), float("nan")
    if n_bootstrap < 1:
        raise ValueError("n_bootstrap must be >= 1")
    rng = np.random.default_rng(seed)
    point = statistic(arr)
    boot = np.empty(n_bootstrap, dtype=float)
    n = arr.size
    for i in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        boot[i] = statistic(arr[idx])
    lo = float(np.quantile(boot, (1 - confidence) / 2))
    hi = float(np.quantile(boot, 1 - (1 - confidence) / 2))
    return float(point), lo, hi


def bootstrap_ci_diff(
    values_a: np.ndarray | list[float],
    values_b: np.ndarray | list[float],
    *,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Bootstrap CI for ``mean(a) - mean(b)`` with paired indices.

    ``values_a`` and ``values_b`` must have the same length and be paired by
    index (same forecast row). Resamples paired indices.
    """
    a = np.asarray(values_a, dtype=float)
    b = np.asarray(values_b, dtype=float)
    if a.size != b.size:
        raise ValueError("a and b must be paired (same length)")
    if a.size == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    point = float(np.mean(a) - np.mean(b))
    boot = np.empty(n_bootstrap, dtype=float)
    n = a.size
    for i in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        boot[i] = float(np.mean(a[idx]) - np.mean(b[idx]))
    lo = float(np.quantile(boot, (1 - confidence) / 2))
    hi = float(np.quantile(boot, 1 - (1 - confidence) / 2))
    return point, lo, hi


__all__ = [
    "Split",
    "expanding_walk_forward_splits",
    "bootstrap_ci",
    "bootstrap_ci_diff",
]
