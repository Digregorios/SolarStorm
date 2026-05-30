"""Track P' (quantization-margin sigma) - proxy + sanity helpers.

Pre-registered in ``contracts/phase5_amendment_trackPprime_quantization_margin.md``
(conformal_method_version 1.4; canonical PREREG sha256
``e4fb58abb8ce63b67527ba4b906c6ab783506220e27c75023a91cc63db07c4e4``).

The single method change vs v1.0 is the difficulty axis::

    frac      = y_pred_dec - floor(y_pred_dec)      # fractional part, in [0, 1)
    margin    = abs(frac - 0.5)                     # distance to the .5 rounding edge
    sigma_hat = 0.5 - margin                        # in [0, 0.5]; LARGER = harder

``Q(x) = floor(x + 0.5)`` is least stable near a half-integer, so distance to that edge is a
difficulty signal that is RNG-free, always defined, label-invariant (depends only on the
fractional part), and independent of the predictive distribution that sank Track P.

The two MANDATORY binding sanity checks (global monotonicity, per-CP distinct) are reused from
``sanity_trackP``. This module adds the margin proxy, a tie-corrected Kendall ``tau-b`` (an
AUXILIARY read-only metric; never pass/fail), and the focus-subset auditor that emits the
reviewer-required ``n_subset`` / tie diagnostics / ``tau-b`` for the 22:00+23:00 regime while the
BINDING pass/fail stays the focus Spearman ``>= min_rho``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from core.eval.sanity_trackP import (
    _average_ranks,
    monotonicity_sanity,
    per_cp_distinct_sanity,
    spearman_rho,
)

__all__ = [
    "margin_sigma_hat",
    "kendall_tau_b",
    "monotonicity_sanity",
    "per_cp_distinct_sanity",
    "focus_subset_audit",
    "spearman_rho",
]


def margin_sigma_hat(y_pred_dec: Sequence[float]) -> np.ndarray:
    """Quantization-margin difficulty axis ``sigma_hat = 0.5 - |frac(y_pred_dec) - 0.5|``.

    Row-aligned to the input. Range ``[0.0, 0.5]``; ``0.5`` exactly on a ``.5`` rounding edge
    (hardest), ``0.0`` exactly on an integer (easiest). Depends ONLY on the fractional part, so
    it is label-invariant under an integer shift of the forecast. No RNG; always defined.
    """
    yp = np.asarray(y_pred_dec, dtype=float)
    frac = yp - np.floor(yp)
    return 0.5 - np.abs(frac - 0.5)


def kendall_tau_b(x: Sequence[float], y: Sequence[float]) -> float:
    """Tie-corrected Kendall ``tau-b`` (AUXILIARY, read-only; never a pass/fail gate).

    More stable than Spearman under the heavy ``abs_error_int`` ties at ``0``, so it is reported
    alongside the binding focus Spearman to interpret a borderline value. Returns ``nan`` when a
    tie correction term vanishes (a fully-constant side). No scipy.
    """
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    n = xa.size
    if n < 2 or ya.size != n:
        return float("nan")
    conc_minus_disc = 0
    for i in range(n - 1):
        dx = np.sign(xa[i + 1 :] - xa[i])
        dy = np.sign(ya[i + 1 :] - ya[i])
        conc_minus_disc += int(np.sum(dx * dy))
    n0 = n * (n - 1) / 2.0
    n1 = _tie_term(xa)
    n2 = _tie_term(ya)
    denom = math.sqrt((n0 - n1) * (n0 - n2))
    if denom == 0.0:
        return float("nan")
    return float(conc_minus_disc / denom)


def _tie_term(a: np.ndarray) -> float:
    """``sum_t t*(t-1)/2`` over tie groups of ``a`` (the tau-b denominator correction)."""
    _, counts = np.unique(a, return_counts=True)
    return float(np.sum(counts * (counts - 1) / 2.0))


def focus_subset_audit(
    sigma_hat: Sequence[float],
    abs_error_int: Sequence[float],
    cp: Sequence[str],
    *,
    focus_cps: Sequence[str],
    min_rho: float,
) -> dict:
    """BINDING focus monotonicity (Spearman ``>= min_rho``) + read-only auditability.

    Restricts to rows whose CP is in ``focus_cps`` (22:00 + 23:00, where the over-coverage
    lives) and runs the focus Spearman check (PASS/FAIL via :func:`monotonicity_sanity`). It
    ALSO emits, without changing the pass/fail logic, the reviewer-required interpretability
    fields: ``n_subset``, ``abs_error_distinct`` (tie diagnostic on the integer error), and
    ``kendall_tau_b`` (auxiliary, non-binding). An empty focus subset fails (cannot verify).
    """
    sig = np.asarray(sigma_hat, dtype=float)
    err = np.asarray(abs_error_int, dtype=float)
    cp_arr = np.asarray([str(c) for c in cp], dtype=object)
    focus = {str(c) for c in focus_cps}
    mask = np.array([c in focus for c in cp_arr], dtype=bool)

    n_subset = int(mask.sum())
    abs_error_distinct = int(np.unique(err[mask]).size) if n_subset else 0
    tau_b = kendall_tau_b(sig[mask], err[mask]) if n_subset >= 2 else float("nan")

    if n_subset == 0:
        mono = {"rho": float("nan"), "min_rho": float(min_rho),
                "require_positive": True, "passed": False}
    else:
        mono = monotonicity_sanity(sig[mask], err[mask], min_rho=min_rho)

    return {
        "n_subset": n_subset,
        "abs_error_distinct": abs_error_distinct,
        "rho": mono["rho"],
        "min_rho": float(min_rho),
        "kendall_tau_b": tau_b,
        "kendall_tau_b_is_binding": False,
        "passed": bool(n_subset > 0 and mono["passed"]),
    }
