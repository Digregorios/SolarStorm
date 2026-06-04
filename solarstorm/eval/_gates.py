"""Frozen gates (G1-G5). Fixed from baseline evaluation, never demotable.

G4 (anti-nowcaster) is hard and non-demotable — the exact gate the old project
demoted to diagnostic (phase4_evaluate.py:95). The lesson is structural.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GateResult:
    gate: str
    description: str
    passed: bool
    status: str   # "OK", "KILL", "NOT_OPERATIONAL", "COLLAPSE_ALERT", "NOWCAST_SUSPECT", "STAY_OUT"
    detail: str


def _g1_null_not_beaten(model_mae: float, best_null_mae: float) -> GateResult:
    passed = model_mae < best_null_mae
    return GateResult(
        gate="G1", description="Null not beaten = KILL",
        passed=passed,
        status="OK" if passed else "KILL",
        detail=f"model_mae={model_mae:.4f} vs best_null_mae={best_null_mae:.4f}",
    )


def _g2_fallback_dominance(fallback_rate: float) -> GateResult:
    passed = fallback_rate <= 0.50
    return GateResult(
        gate="G2", description="Fallback dominance > 50% = NOT_OPERATIONAL",
        passed=passed,
        status="OK" if passed else "NOT_OPERATIONAL",
        detail=f"fallback_rate={fallback_rate:.4f}",
    )


def _g3_p50_collapse(p50_mode_share: float) -> GateResult:
    passed = p50_mode_share <= 0.50
    return GateResult(
        gate="G3", description="p50 collapse = COLLAPSE_ALERT",
        passed=passed,
        status="OK" if passed else "COLLAPSE_ALERT",
        detail=f"p50_mode_share={p50_mode_share:.4f}",
    )


def _g4_anti_nowcaster(
    corr_diff: float | None,
    corr_diff_ci95: tuple[float, float] | None = None,
) -> GateResult:
    if corr_diff is None:
        # Non-demotable: a missing discriminant cannot CLEAR the gate. Surface
        # it as a failing G4, never let it vanish (the old project's failure).
        passed = False
        detail = "corr_diff unavailable — cannot clear anti-nowcaster gate"
    elif corr_diff_ci95 is not None:
        lo, hi = corr_diff_ci95
        passed = corr_diff >= 0.05 and lo > 0.0
        detail = f"corr_diff={corr_diff:.4f}, ci95=[{lo:.4f}, {hi:.4f}]"
    else:
        passed = corr_diff >= 0.05
        detail = f"corr_diff={corr_diff:.4f} (no CI)"
    return GateResult(
        gate="G4", description="Anti-nowcaster — hard, non-demotable",
        passed=passed,
        status="OK" if passed else "NOWCAST_SUSPECT",
        detail=detail,
    )


def _g5_per_cp(cp: str, per_cp_passed: bool) -> GateResult:
    return GateResult(
        gate="G5", description="Best-null per CP",
        passed=per_cp_passed,
        status="OK" if per_cp_passed else "STAY_OUT",
        detail=f"CP={cp}: {'beats null' if per_cp_passed else 'loses to null → stay_out'}",
    )


def apply_all_gates(
    *,
    model_mae: float,
    best_null_mae: float,
    cp: str,
    fallback_rate: float = 0.0,
    p50_mode_share: float = 0.0,
    corr_diff: float | None = None,
    corr_diff_ci95: tuple[float, float] | None = None,
    per_cp_passed: bool = True,
) -> dict[str, GateResult]:
    results = {
        "G1": _g1_null_not_beaten(model_mae, best_null_mae),
        "G2": _g2_fallback_dominance(fallback_rate),
        "G3": _g3_p50_collapse(p50_mode_share),
        "G4": _g4_anti_nowcaster(corr_diff, corr_diff_ci95),
        "G5": _g5_per_cp(cp, per_cp_passed),
    }
    return results
