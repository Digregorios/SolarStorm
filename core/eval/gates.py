"""Pre-registered anti-nowcaster gates (REQ-AUD-2 + REQ-MET-4 kill criterion).

Thresholds are FROZEN before seeing results. Each gate returns a dict with
``passed`` (bool/None), ``value`` (point estimate) and ``ci`` (low/high or None).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from core.eval.cv import bootstrap_ci, bootstrap_ci_diff
from core.eval.metrics import corr, per_row_squared_error


@dataclass
class GateResult:
    name: str
    passed: bool | None
    value: float
    ci_low: float | None
    ci_high: float | None
    threshold: float | str
    details: dict[str, Any]


# Frozen thresholds (REQ-AUD-2).
SS_1H_MIN = 0.08
SS_3H_MIN = 0.10
CORR_DIFF_MIN = 0.20
COVERAGE_TOL = 0.04
I_T_OBS_MAX = 0.10
COUNTERFACTUAL_AUC_MIN = 0.70


def _ss_from_errors(err_pred_sq: np.ndarray, err_base_sq: np.ndarray) -> np.ndarray:
    """Per-row contribution: 1 - (err_pred / err_base) is unstable per row.

    Instead we use a paired bootstrap: SS = 1 - mean(err_pred) / mean(err_base).
    This helper returns the row-wise pair (err_pred_sq, err_base_sq).
    """
    return np.column_stack([err_pred_sq, err_base_sq])


def gate_ss_vs_persistence(
    pred_int: np.ndarray,
    persistence_int: np.ndarray,
    truth_int: np.ndarray,
    *,
    label: str,
    threshold: float,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> GateResult:
    err_p = per_row_squared_error(pred_int.astype(float), truth_int.astype(float))
    err_b = per_row_squared_error(persistence_int.astype(float), truth_int.astype(float))
    if err_p.size == 0:
        return GateResult(label, None, float("nan"), None, None, threshold, {"reason": "empty"})
    point_ss = 1.0 - float(np.mean(err_p) / np.mean(err_b)) if np.mean(err_b) > 0 else float("nan")
    # Vectorised paired bootstrap (review-v2 #N2): idx_mat shape (n_bootstrap, n).
    n = err_p.size
    rng = np.random.default_rng(seed)
    idx_mat = rng.integers(0, n, size=(n_bootstrap, n))
    mb = err_b[idx_mat].mean(axis=1)
    mp = err_p[idx_mat].mean(axis=1)
    boots = np.where(mb == 0, np.nan, 1.0 - mp / mb)
    lo = float(np.nanquantile(boots, 0.025))
    hi = float(np.nanquantile(boots, 0.975))
    passed = point_ss > threshold and lo > 0.0
    return GateResult(label, passed, point_ss, lo, hi, threshold, {"n": int(n)})


def gate_corr_diff(
    pred_latent: np.ndarray,
    truth_int: np.ndarray,
    t_now: np.ndarray,
    *,
    threshold: float = CORR_DIFF_MIN,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> GateResult:
    """Gate on `corr(pred, truth) - corr(pred, T_now)` (REQ-AUD-2).

    review-v2 #N3: paired bootstrap CI over rows. The gate now requires both
    the point estimate to exceed ``threshold`` AND the lower bound of the
    bootstrap CI95% to exceed zero, in line with ``gate_ss_vs_persistence``.
    """
    pred = np.asarray(pred_latent, dtype=float)
    truth = np.asarray(truth_int, dtype=float)
    now = np.asarray(t_now, dtype=float)
    if pred.size != truth.size or pred.size != now.size:
        raise ValueError("pred / truth / t_now length mismatch")
    c_truth = corr(pred, truth)
    c_now = corr(pred, now)
    diff = c_truth - c_now

    # Vectorised paired bootstrap of the correlation difference.
    n = pred.size
    if n < 4:
        return GateResult(
            name="corr_diff",
            passed=False,
            value=diff,
            ci_low=None,
            ci_high=None,
            threshold=threshold,
            details={"corr_truth": c_truth, "corr_now": c_now, "reason": "n<4"},
        )
    rng = np.random.default_rng(seed)
    idx_mat = rng.integers(0, n, size=(n_bootstrap, n))
    p_b = pred[idx_mat]
    t_b = truth[idx_mat]
    n_b = now[idx_mat]
    # Pearson correlation along axis=1 vectorised.
    def _corr_axis1(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        a_centered = a - a.mean(axis=1, keepdims=True)
        b_centered = b - b.mean(axis=1, keepdims=True)
        num = (a_centered * b_centered).sum(axis=1)
        den = np.sqrt((a_centered ** 2).sum(axis=1) * (b_centered ** 2).sum(axis=1))
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(den > 0, num / den, np.nan)

    boots = _corr_axis1(p_b, t_b) - _corr_axis1(p_b, n_b)
    lo = float(np.nanquantile(boots, 0.025))
    hi = float(np.nanquantile(boots, 0.975))
    passed = diff >= threshold and lo > 0.0
    return GateResult(
        name="corr_diff",
        passed=passed,
        value=diff,
        ci_low=lo,
        ci_high=hi,
        threshold=threshold,
        details={"corr_truth": c_truth, "corr_now": c_now, "n": int(n)},
    )


def gate_coverage_ic80(
    truth_int: np.ndarray,
    ic80_low: np.ndarray,
    ic80_high: np.ndarray,
    *,
    target: float = 0.80,
    tol: float = COVERAGE_TOL,
    skip_reason: str | None = None,
) -> GateResult:
    inside = (truth_int >= ic80_low) & (truth_int <= ic80_high)
    cov = float(np.mean(inside))
    if skip_reason:
        return GateResult(
            name="coverage_ic80",
            passed=None,
            value=cov,
            ci_low=None,
            ci_high=None,
            threshold=f"|cov-{target}|<{tol}",
            details={"target": target, "skipped": skip_reason},
        )
    return GateResult(
        name="coverage_ic80",
        passed=abs(cov - target) < tol,
        value=cov,
        ci_low=None,
        ci_high=None,
        threshold=f"|cov-{target}|<{tol}",
        details={"target": target},
    )


def gate_i_t_obs(value: float, *, threshold: float = I_T_OBS_MAX) -> GateResult:
    return GateResult(
        name="i_t_obs",
        passed=value < threshold,
        value=float(value),
        ci_low=None,
        ci_high=None,
        threshold=f"< {threshold}",
        details={},
    )


def gate_counterfactual(value: float, *, threshold: float = COUNTERFACTUAL_AUC_MIN) -> GateResult:
    return GateResult(
        name="counterfactual_same_temp",
        passed=value > threshold,
        value=float(value),
        ci_low=None,
        ci_high=None,
        threshold=f"> {threshold}",
        details={},
    )


def asdict_safe(g: GateResult) -> dict[str, Any]:
    """Convert GateResult to a JSON-safe dict."""
    return asdict(g)


__all__ = [
    "GateResult",
    "SS_1H_MIN",
    "SS_3H_MIN",
    "CORR_DIFF_MIN",
    "COVERAGE_TOL",
    "I_T_OBS_MAX",
    "COUNTERFACTUAL_AUC_MIN",
    "gate_ss_vs_persistence",
    "gate_corr_diff",
    "gate_coverage_ic80",
    "gate_i_t_obs",
    "gate_counterfactual",
    "asdict_safe",
]
