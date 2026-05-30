"""NWP-specific Frozen observation test (REQ-AUD-4 + reforco B).

Extends audit phase 2 (frozen_obs) with a dedicated check for NWP snapshots:
every row consumed at a given CP MUST satisfy
``run_time_utc <= cp_utc - safety_margin``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import polars as pl


def run_phase(
    *,
    nwp_selections: list[dict[str, Any]],
    safety_margin: timedelta = timedelta(minutes=60),
) -> dict[str, Any]:
    """Validate every NWP selection used in forecasts.

    ``nwp_selections`` must be a list of dicts with ``cp_utc`` and
    ``run_time_utc`` (tz-aware UTC datetimes), ``model``, ``valid_time_utc``,
    ``lead_h``.
    """
    if not nwp_selections:
        return {"phase": "frozen_obs_nwp", "passed": None,
                "details": {"reason": "no NWP selections"}}
    violations = []
    for s in nwp_selections:
        cp = s.get("cp_utc")
        rt = s.get("run_time_utc")
        if cp is None or rt is None:
            violations.append({"reason": "missing_field", "row": str(s)})
            continue
        if rt > cp - safety_margin:
            violations.append({
                "model": s.get("model"),
                "cp_utc": cp.isoformat(),
                "run_time_utc": rt.isoformat(),
                "delta_min": int((rt - (cp - safety_margin)).total_seconds() // 60),
            })
    return {
        "phase": "frozen_obs_nwp",
        "passed": len(violations) == 0,
        "details": {
            "n_checked": len(nwp_selections),
            "n_violations": len(violations),
            "safety_margin_minutes": int(safety_margin.total_seconds() // 60),
            "violations_sample": violations[:5],
        },
    }


__all__ = ["run_phase"]
