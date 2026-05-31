"""Evaluation metrics (REQ-MET-2, REQ-AUD-2)."""

from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np


def bracket_match_at_p50(p50: np.ndarray, truth: np.ndarray) -> float:
    """Share of rows where ``int(p50) == int(truth)``."""
    p = np.asarray(p50, dtype=int)
    t = np.asarray(truth, dtype=int)
    if p.size != t.size:
        raise ValueError("p50 and truth length mismatch")
    if p.size == 0:
        return float("nan")
    return float(np.mean(p == t))


def bracket_match_at_coverage(
    prob_dists: Iterable[Mapping[int, float]],
    truth: Iterable[int],
    *,
    coverage: float = 0.5,
) -> float:
    """Share of rows where truth falls inside the smallest credible set with
    cumulative mass >= coverage (sorted by prob descending)."""
    pds = list(prob_dists)
    truths = list(truth)
    if not pds:
        return float("nan")
    if len(pds) != len(truths):
        raise ValueError("prob_dists / truth length mismatch")
    if not 0.0 < coverage <= 1.0:
        raise ValueError("coverage must be in (0, 1]")
    hits = 0
    for pd, t in zip(pds, truths, strict=True):
        sorted_items = sorted(pd.items(), key=lambda kv: -kv[1])
        cum = 0.0
        covered: set[int] = set()
        for k, p in sorted_items:
            cum += p
            covered.add(int(k))
            if cum >= coverage:
                break
        if int(t) in covered:
            hits += 1
    return hits / len(pds)


def skill_score(
    pred: np.ndarray,
    baseline: np.ndarray,
    truth: np.ndarray,
) -> float:
    """SS = 1 - MSE(pred) / MSE(baseline). Positive => pred beats baseline."""
    p = np.asarray(pred, dtype=float)
    b = np.asarray(baseline, dtype=float)
    t = np.asarray(truth, dtype=float)
    err_p = float(np.mean((p - t) ** 2))
    err_b = float(np.mean((b - t) ** 2))
    if err_b == 0.0:
        return float("nan")
    return 1.0 - err_p / err_b


def per_row_squared_error(pred: np.ndarray, truth: np.ndarray) -> np.ndarray:
    p = np.asarray(pred, dtype=float)
    t = np.asarray(truth, dtype=float)
    return (p - t) ** 2


def mae(pred: np.ndarray, truth: np.ndarray) -> float:
    """Mean absolute error in degC between point forecast and truth."""
    p = np.asarray(pred, dtype=float)
    t = np.asarray(truth, dtype=float)
    if p.size != t.size:
        raise ValueError("pred and truth length mismatch")
    if p.size == 0:
        return float("nan")
    return float(np.mean(np.abs(p - t)))


def rmse(pred: np.ndarray, truth: np.ndarray) -> float:
    """Root mean squared error in degC between point forecast and truth."""
    p = np.asarray(pred, dtype=float)
    t = np.asarray(truth, dtype=float)
    if p.size != t.size:
        raise ValueError("pred and truth length mismatch")
    if p.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean((p - t) ** 2)))


def corr(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation; NaN if degenerate."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    a = a[mask]
    b = b[mask]
    if a.size < 2:
        return float("nan")
    sa = float(np.std(a))
    sb = float(np.std(b))
    if sa == 0.0 or sb == 0.0:
        return float("nan")
    return float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))


def rps(prob_dist: Mapping[int, float], truth: int) -> float:
    """Ranked Probability Score for a single discrete prediction."""
    sorted_k = sorted(prob_dist.keys())
    cum_p = 0.0
    cum_o = 0.0
    score = 0.0
    for k in sorted_k:
        cum_p += float(prob_dist[k])
        cum_o += 1.0 if k == int(truth) else 0.0
        score += (cum_p - cum_o) ** 2
    return score


__all__ = [
    "bracket_match_at_p50",
    "bracket_match_at_coverage",
    "skill_score",
    "per_row_squared_error",
    "mae",
    "rmse",
    "corr",
    "rps",
]
