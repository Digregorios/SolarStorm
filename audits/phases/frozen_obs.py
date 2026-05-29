"""Phase 2: Frozen observation test (REQ-AUD-4)."""

from __future__ import annotations

from typing import Any


def run_phase(*, forecasts: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify feature_max_ts < cp_utc for every forecast row."""
    violations = []
    for fc in forecasts:
        fmax = fc.get("feature_max_ts_utc")
        cp = fc.get("cp_utc")
        if fmax is None or cp is None:
            continue
        if fmax >= cp:
            violations.append({"cp_utc": cp.isoformat(), "feature_max_ts": fmax.isoformat()})
    return {
        "phase": "frozen_obs",
        "passed": len(violations) == 0,
        "details": {"n_checked": len(forecasts), "n_violations": len(violations)},
    }
