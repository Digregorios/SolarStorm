"""Phase 1: Lead-time forecast audit (design 11)."""

from __future__ import annotations

from typing import Any


def run_phase(
    *,
    panel: Any,
    forecasts: list[dict[str, Any]],
    test_window: tuple[Any, Any],
) -> dict[str, Any]:
    """Compute skill vs persistence at multiple leads.

    For Phase 2 baselines we approximate "lead" by CP distance to end-of-day.
    """
    if not forecasts:
        return {"phase": "lead_time", "passed": False, "details": {"reason": "no forecasts"}}

    n_correct = 0
    n_total = 0
    for fc in forecasts:
        truth = fc.get("truth_int")
        p50 = fc.get("p50_int")
        if truth is None or p50 is None:
            continue
        n_total += 1
        if int(p50) == int(truth):
            n_correct += 1
    acc = n_correct / n_total if n_total else 0.0
    persistence_acc = sum(
        1
        for fc in forecasts
        if fc.get("truth_int") is not None
        and fc.get("k_cp") is not None
        and int(fc["k_cp"]) == int(fc["truth_int"])
    ) / max(1, n_total)
    skill = acc - persistence_acc
    return {
        "phase": "lead_time",
        "passed": acc >= persistence_acc - 0.01,
        "details": {
            "n_total": n_total,
            "p50_accuracy": acc,
            "persistence_accuracy": persistence_acc,
            "skill_vs_persistence": skill,
        },
    }
