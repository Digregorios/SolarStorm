"""Native integer conformal calibration (T-9-5, native_integer_conformal_v0).

Two calibrators that produce integer IC80 intervals WITHOUT applying Q to
decimal bounds. Endpoints are integers by construction.

M1: symmetric absolute-residual quantile.
M2: asymmetric signed-residual quantiles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class IntegerAbsResult:
    """Fitted M1 (symmetric) calibrator."""
    q: int
    n_calib: int


@dataclass(frozen=True)
class IntegerSignedResult:
    """Fitted M2 (asymmetric) calibrator."""
    q_lo: int
    q_hi: int
    n_calib: int


def fit_integer_abs(resid_int: np.ndarray, coverage: float = 0.80) -> IntegerAbsResult:
    """M1: symmetric integer conformal from |y_int - pred_int|.

    q = ceil((n+1)*coverage)-th order statistic of |resid_int|.
    Interval: [pred_int - q, pred_int + q].
    """
    r = np.asarray(resid_int, dtype=int)
    n = r.size
    if n == 0:
        raise ValueError("cannot calibrate on empty residuals")
    absvals = np.sort(np.abs(r))
    rank = math.ceil((n + 1) * coverage)
    rank = min(max(rank, 1), n)
    q = int(absvals[rank - 1])
    return IntegerAbsResult(q=q, n_calib=n)


def fit_integer_signed(resid_int: np.ndarray, coverage: float = 0.80) -> IntegerSignedResult:
    """M2: asymmetric integer conformal from signed (y_int - pred_int).

    alpha = 1 - coverage.
    q_lo = floor((n+1)*(alpha/2))-th order statistic of signed residuals.
    q_hi = ceil((n+1)*(1 - alpha/2))-th order statistic of signed residuals.
    Interval: [pred_int + q_lo, pred_int + q_hi].
    """
    r = np.asarray(resid_int, dtype=int)
    n = r.size
    if n == 0:
        raise ValueError("cannot calibrate on empty residuals")
    s = np.sort(r)
    alpha = 1.0 - coverage
    rank_lo = math.floor((n + 1) * (alpha / 2.0))
    rank_hi = math.ceil((n + 1) * (1.0 - alpha / 2.0))
    rank_lo = min(max(rank_lo, 1), n)
    rank_hi = min(max(rank_hi, 1), n)
    q_lo = int(s[rank_lo - 1])
    q_hi = int(s[rank_hi - 1])
    return IntegerSignedResult(q_lo=q_lo, q_hi=q_hi, n_calib=n)


def apply_integer_abs(result: IntegerAbsResult, pred_int: np.ndarray):
    """Apply M1: returns (lo_int, hi_int) arrays."""
    p = np.asarray(pred_int, dtype=int)
    return p - result.q, p + result.q


def apply_integer_signed(result: IntegerSignedResult, pred_int: np.ndarray):
    """Apply M2: returns (lo_int, hi_int) arrays."""
    p = np.asarray(pred_int, dtype=int)
    return p + result.q_lo, p + result.q_hi


__all__ = [
    "IntegerAbsResult",
    "IntegerSignedResult",
    "fit_integer_abs",
    "fit_integer_signed",
    "apply_integer_abs",
    "apply_integer_signed",
]
