"""Track P proxy + MANDATORY pre-run sanity checks (Phase 5 amendment 1.3).

Pre-registered in ``contracts/phase5_amendment_trackP_predictive_uncertainty.md``
(criterion_version 1.0; canonical PREREG sha256 pinned as ``PHASE5P_COMMITTED_SHA256``).
Track P replaces the difficulty axis ``sigma_hat = sqrt(p50_var)`` with the Shannon
entropy (in nats) of the model's OWN emitted integer predictive distribution:

    sigma_hat = uncertainty(prob_dist) = - sum_k p_k * ln(p_k),  with 0 * ln(0) := 0.

Entropy is LABEL-INVARIANT (depends only on the probability profile, not on where the
integer support sits) and discrete-stable, the property the reviewer required over raw
``std``. It is RAW (no normalization), always defined, deterministic, and RNG-free.

Before the single ``phase5_evaluate`` one-shot is permitted, two read-only, CALIB-ONLY,
PER-SPLIT sanity checks MUST pass (reviewer-required, frozen thresholds):

  1. Monotonicity: Spearman ``rho(sigma_hat, abs_error_int)`` POSITIVE and ``>= 0.10``,
     where ``abs_error_int = |y_true_int - Q(y_pred_dec)|``. A difficulty axis that does
     not even rank-order the model's own integer error is not a difficulty axis.
  2. No per-CP collapse: every CP (explicitly 22:00 and 23:00, the late-CP regime where
     the over-coverage lives) has ``>= 3`` distinct calib ``sigma_hat`` values. A proxy
     that collapses within the late-CP regime cannot differentiate the rows that fail the
     het gate.

A failed check REJECTS the proxy: the one-shot is NOT run, the result is registered as a
"proxy rejected", and a NEW pre-registered hypothesis (Track P') is opened. The thresholds
are frozen in the hashed PREREG block and are NEVER re-tuned after looking. No RNG; all
helpers are deterministic (sorting only).
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np


def prob_dist_entropy(prob_dist: Mapping[int, float]) -> float:
    """Shannon entropy in nats of an integer predictive distribution (RAW, no norm).

    ``- sum_k p_k * ln(p_k)`` with the convention ``0 * ln(0) := 0`` (terms with
    ``p_k <= 0`` are skipped). Natural log -> nats, as pre-registered. Label-invariant:
    only the probability profile matters. Corners: one-hot -> ``0.0``; uniform over a
    support of size ``m`` -> ``ln(m)``.
    """
    h = 0.0
    for p in prob_dist.values():
        pf = float(p)
        if pf > 0.0:
            h -= pf * math.log(pf)
    return h


def entropy_sigma_hat(prob_dists: Sequence[Mapping[int, float]]) -> np.ndarray:
    """Row-aligned ``sigma_hat = entropy(prob_dist)`` (nats) for a list of prob_dists."""
    return np.asarray([prob_dist_entropy(pd) for pd in prob_dists], dtype=float)


def _average_ranks(a: np.ndarray) -> np.ndarray:
    """Tie-aware average (fractional) ranks, 1-based - matches scipy ``rankdata``.

    Deterministic (stable sort). Ties receive the average of the ranks they span, so the
    Spearman built on these ranks equals the standard tie-corrected coefficient.
    """
    a = np.asarray(a, dtype=float)
    n = a.size
    order = np.argsort(a, kind="mergesort")
    sorted_a = a[order]
    ranks = np.empty(n, dtype=float)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # average of 1-based ranks i+1..j+1
        ranks[order[i : j + 1]] = avg
        i = j + 1
    return ranks


def spearman_rho(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman rank correlation (tie-corrected; no scipy). ``nan`` if a side is constant.

    Equivalent to Pearson correlation of the tie-aware average ranks. Deterministic.
    """
    xr = _average_ranks(np.asarray(x, dtype=float))
    yr = _average_ranks(np.asarray(y, dtype=float))
    if xr.size != yr.size:
        raise ValueError(f"x and y must be same length; got {xr.size}, {yr.size}")
    if xr.size == 0:
        return float("nan")
    xc = xr - xr.mean()
    yc = yr - yr.mean()
    denom = math.sqrt(float((xc * xc).sum()) * float((yc * yc).sum()))
    if denom == 0.0:  # a side has no rank variance (all equal) -> undefined
        return float("nan")
    return float((xc * yc).sum() / denom)


def monotonicity_sanity(
    sigma_hat: Sequence[float],
    abs_error_int: Sequence[float],
    *,
    min_rho: float,
    require_positive: bool = True,
) -> dict:
    """Sanity check 1: Spearman ``rho(sigma_hat, abs_error_int)`` positive and ``>= min_rho``.

    ``abs_error_int = |y_true_int - Q(y_pred_dec)|`` (the model's own integer error). A
    ``nan`` rho (constant side) fails. Read-only; returns the rho and the pass flag.
    """
    rho = spearman_rho(sigma_hat, abs_error_int)
    passed = (
        math.isfinite(rho)
        and rho >= float(min_rho)
        and ((rho > 0.0) if require_positive else True)
    )
    return {
        "rho": rho,
        "min_rho": float(min_rho),
        "require_positive": bool(require_positive),
        "passed": bool(passed),
    }


def per_cp_distinct_sanity(
    sigma_hat: Sequence[float],
    cp: Sequence[str],
    *,
    focus_cps: Sequence[str],
    min_distinct: int,
) -> dict:
    """Sanity check 2: every CP has ``>= min_distinct`` distinct calib ``sigma_hat`` values.

    The ``focus_cps`` (22:00 / 23:00, the late-CP regime) must additionally be PRESENT in
    calib - a missing focus CP cannot be verified and fails. Read-only; returns per-CP
    distinct counts, focus presence, and the pass flag.
    """
    sig = np.asarray(sigma_hat, dtype=float)
    cps = list(cp)
    if sig.size != len(cps):
        raise ValueError(f"sigma_hat and cp must be same length; got {sig.size}, {len(cps)}")
    cp_arr = np.asarray(cps, dtype=object)
    by_cp_distinct: dict[str, int] = {}
    for key in dict.fromkeys(cps):  # stable unique order
        mask = cp_arr == key
        by_cp_distinct[str(key)] = int(np.unique(sig[mask]).size)

    min_d = int(min_distinct)
    all_ok = all(v >= min_d for v in by_cp_distinct.values())
    focus_present = {str(fc): (str(fc) in by_cp_distinct) for fc in focus_cps}
    focus_ok = all(by_cp_distinct.get(str(fc), 0) >= min_d for fc in focus_cps)
    return {
        "by_cp_distinct": by_cp_distinct,
        "min_distinct": min_d,
        "focus_cps": [str(fc) for fc in focus_cps],
        "focus_present": focus_present,
        "all_cps_pass": bool(all_ok),
        "focus_cps_pass": bool(focus_ok),
        "passed": bool(all_ok and focus_ok),
    }


__all__ = [
    "prob_dist_entropy",
    "entropy_sigma_hat",
    "spearman_rho",
    "monotonicity_sanity",
    "per_cp_distinct_sanity",
]
