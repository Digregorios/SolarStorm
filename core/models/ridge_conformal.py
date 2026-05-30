"""Ridge conformal-minimal: per-CP IC80 from the Ridge's own absolute residuals.

NOT Phase 5 / full calibration. This is an auditable BRIDGE (``ridge_conformal_minimal``):
the Ridge stays responsible for the center ``p50_int = Q(T_latent_dec)``; the IC80 is the
80% conformal quantile of the Ridge's OWN integer absolute residuals
``|truth_int - p50_int|``, computed per CP on a held-out/recent calibration window (split
conformal). Symmetric integer interval ``[p50 - q, p50 + q]``.

Hierarchical fallback (per update.txt 2026-05-30): CP-specific quantile if the CP has
``>= n_min`` calibration rows, else the pooled all-CP quantile, else ``insufficient_data``.
``conformal_source`` records which path each interval used. Deterministic (sorting only).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class CpConformalCalibrator:
    """Per-CP + pooled 80% conformal quantiles of integer abs-residuals."""

    coverage: float
    n_min: int
    q_by_cp: dict[str, int] = field(default_factory=dict)
    n_by_cp: dict[str, int] = field(default_factory=dict)
    q_global: int | None = None
    n_global: int = 0


def _conformal_abs_quantile(abs_resid: np.ndarray, coverage: float) -> int:
    """Finite-sample conformal quantile of integer abs-residuals at ``coverage``.

    Rank ``ceil((n+1)*coverage)`` (clamped to n) on the sorted abs-residuals -> the smallest
    integer half-width whose symmetric interval covers ``>= coverage`` of calibration rows.
    """
    s = np.sort(np.asarray(abs_resid, dtype=int))
    n = s.size
    rank = int(math.ceil((n + 1) * coverage))
    return int(s[min(max(rank, 1), n) - 1])


def fit_cp_abs_conformal(
    abs_residuals: Sequence[int],
    cps: Sequence[str],
    *,
    coverage: float = 0.80,
    n_min: int = 30,
) -> CpConformalCalibrator:
    """Fit per-CP + pooled conformal half-widths from integer abs-residuals."""
    a = np.asarray(abs_residuals, dtype=int)
    cp_arr = np.asarray(list(cps), dtype=object)
    if a.size != cp_arr.size:
        raise ValueError(f"abs_residuals and cps must match; got {a.size}, {cp_arr.size}")
    if a.size == 0:
        return CpConformalCalibrator(coverage=coverage, n_min=n_min)
    q_by_cp: dict[str, int] = {}
    n_by_cp: dict[str, int] = {}
    for cp in dict.fromkeys(cps):
        mask = cp_arr == cp
        n = int(mask.sum())
        n_by_cp[cp] = n
        if n >= 1:
            q_by_cp[cp] = _conformal_abs_quantile(a[mask], coverage)
    return CpConformalCalibrator(
        coverage=coverage, n_min=n_min, q_by_cp=q_by_cp, n_by_cp=n_by_cp,
        q_global=_conformal_abs_quantile(a, coverage), n_global=int(a.size),
    )


def interval(cal: CpConformalCalibrator, p50_int: int, cp: str) -> tuple[int, int, str]:
    """Return ``(ic80_low_int, ic80_high_int, conformal_source)`` for one row.

    source: ``cp_specific`` (CP has >= n_min calib rows), ``global_cp_pool`` (fallback),
    or ``insufficient_data`` (no calibration at all -> degenerate point interval).
    """
    if cal.n_by_cp.get(cp, 0) >= cal.n_min and cp in cal.q_by_cp:
        q, source = cal.q_by_cp[cp], "cp_specific"
    elif cal.q_global is not None:
        q, source = cal.q_global, "global_cp_pool"
    else:
        return int(p50_int), int(p50_int), "insufficient_data"
    return int(p50_int) - int(q), int(p50_int) + int(q), source


__all__ = ["CpConformalCalibrator", "fit_cp_abs_conformal", "interval"]
