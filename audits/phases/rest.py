"""Phases 3-7 of the H0 audit (Phase 2 stubs; sharpened in later phases)."""

from __future__ import annotations

import math
from typing import Any


def counterfactual_same_temp(*, forecasts: list[dict[str, Any]]) -> dict[str, Any]:
    """Phase 3: pairs sharing k_cp but with different regimes/months should still
    yield separable predictions. Without a regime engine yet (Phase 4+) we report
    a placeholder using month as a proxy."""
    if not forecasts:
        return {"phase": "counterfactual_same_temp", "passed": None, "details": {"reason": "no data"}}
    by_kcp: dict[int, list[dict[str, Any]]] = {}
    for fc in forecasts:
        kcp = fc.get("k_cp")
        if kcp is None:
            continue
        by_kcp.setdefault(int(kcp), []).append(fc)
    pairs_var = []
    for kcp, group in by_kcp.items():
        if len(group) < 2:
            continue
        months = {fc.get("month") for fc in group}
        if len(months) > 1:
            preds = [int(fc.get("p50_int")) for fc in group if fc.get("p50_int") is not None]
            if preds:
                avg = sum(preds) / len(preds)
                var = sum((p - avg) ** 2 for p in preds) / len(preds)
                pairs_var.append(var)
    auc_proxy = (
        min(1.0, max(0.0, sum(pairs_var) / len(pairs_var) / 4.0)) if pairs_var else 0.0
    )
    return {
        "phase": "counterfactual_same_temp",
        "passed": auc_proxy >= 0.10,
        "details": {"n_buckets": len(by_kcp), "auc_proxy": auc_proxy},
    }


def no_temperature_model(*, forecasts: list[dict[str, Any]]) -> dict[str, Any]:
    """Phase 4: skip until Phase 4 in plan; mark as 'skipped'."""
    return {
        "phase": "no_temperature_model",
        "passed": None,
        "details": {"reason": "skipped - activated in Phase 3 of plan (T-3-6)"},
    }


def horizon_degradation(*, forecasts: list[dict[str, Any]]) -> dict[str, Any]:
    """Phase 5: compare accuracy across CPs. Pass if monotonic up to noise."""
    by_cp: dict[str, list[bool]] = {}
    for fc in forecasts:
        cp = fc.get("cp_hhmm")
        truth = fc.get("truth_int")
        p50 = fc.get("p50_int")
        if cp is None or truth is None or p50 is None:
            continue
        by_cp.setdefault(cp, []).append(int(p50) == int(truth))
    rows = sorted(by_cp.items())
    accs = [(cp, sum(v) / len(v)) for cp, v in rows if v]
    monotonic_ok = all(accs[i][1] <= accs[i + 1][1] + 0.05 for i in range(len(accs) - 1))
    return {
        "phase": "horizon_degradation",
        "passed": bool(monotonic_ok and accs),
        "details": {"per_cp_accuracy": accs},
    }


def extreme_spike(*, forecasts: list[dict[str, Any]]) -> dict[str, Any]:
    """Phase 6: tail audit on |truth - p50| >= 2."""
    big = [
        fc for fc in forecasts
        if fc.get("truth_int") is not None
        and fc.get("p50_int") is not None
        and abs(int(fc["truth_int"]) - int(fc["p50_int"])) >= 2
    ]
    rate = len(big) / max(1, len(forecasts))
    return {
        "phase": "extreme_spike",
        "passed": rate < 0.30,
        "details": {"n_big_errors": len(big), "rate": rate},
    }


def economic_edge(*, forecasts: list[dict[str, Any]]) -> dict[str, Any]:
    """Phase 7: skipped until Phase 8 of plan."""
    return {
        "phase": "economic_edge",
        "passed": None,
        "details": {"reason": "skipped - activated in Phase 8 (T-8-6)"},
    }
