"""T-11-7 ECMWF daily-per-CP causal coverage audit (read-only, no fetch).

Strengthens the base before any modeling: for EVERY local date 2024-03-01..2025-12-31 and EVERY CP
(20/21/22/23 UTC), verify select_nwp_v1 returns a CAUSAL run (run_time <= cp - 60min). Reports daily
coverage per CP, any gaps, and the lead_h distribution per CP. Uses the already-local snapshots.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from core.contracts.station import load_station_config
from core.ingest.nwp import read_snapshots, select_nwp_v1
from core.ingest.nwp_client import ECMWF_IFS_HRES
from core.io.timeutil import cp_to_utc

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "artifacts" / "raw" / "nwp"
START, END = date(2024, 3, 1), date(2025, 12, 31)
CP_SET = ["20:00", "21:00", "22:00", "23:00"]
SAFETY = timedelta(minutes=60)


def main() -> int:
    load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    snaps = read_snapshots(station="NZWN", model=ECMWF_IFS_HRES, endpoint="single_runs",
                           out_root=OUT_ROOT)
    per_cp = {cp: {"n": 0, "causal": 0, "leads": [], "gaps": []} for cp in CP_SET}
    d = START
    while d <= END:
        for cp in CP_SET:
            cp_utc = cp_to_utc(d, cp)
            per_cp[cp]["n"] += 1
            sel = select_nwp_v1(snaps, cp_utc=cp_utc, target_valid_utc=cp_utc, safety_margin=SAFETY)
            if sel is not None and sel.run_time_utc <= cp_utc - SAFETY:
                per_cp[cp]["causal"] += 1
                per_cp[cp]["leads"].append(int(sel.lead_h))
            else:
                per_cp[cp]["gaps"].append(d.isoformat())
        d += timedelta(days=1)

    summary = {}
    for cp, v in per_cp.items():
        leads = np.array(v["leads"]) if v["leads"] else np.array([0])
        summary[cp] = {
            "n_days": v["n"], "causal": v["causal"],
            "coverage": round(v["causal"] / v["n"], 4) if v["n"] else 0.0,
            "n_gaps": len(v["gaps"]), "gaps_first5": v["gaps"][:5],
            "lead_h_min": int(leads.min()), "lead_h_median": float(np.median(leads)),
            "lead_h_max": int(leads.max()),
        }
    all_full = all(s["coverage"] >= 0.99 for s in summary.values())
    all_causal = all(s["causal"] == s["n_days"] for s in summary.values())
    out = {
        "audit": "ecmwf_daily_cp_coverage", "window": [START.isoformat(), END.isoformat()],
        "per_cp": summary, "all_cp_coverage_ge_0_99": all_full,
        "all_selected_runs_causal": all_causal,
        "verdict": "GO" if all_full and all_causal else "PAUSE",
        "note": "Read-only daily audit over local snapshots; no fetch, no model. run_time <= cp-60min "
                "enforced by select_nwp_v1; every selected run re-checked here.",
    }
    rep = REPO / "reports" / "nwp"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "ecmwf_full_daily_cp_coverage.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    (rep / "ecmwf_full_daily_cp_coverage.md").write_text(_render(out), encoding="ascii")
    print(f"VERDICT {out['verdict']} | all_cov>=0.99 {all_full} | all_causal {all_causal}")
    for cp, s in summary.items():
        print(f"  {cp}: cov {s['coverage']} ({s['causal']}/{s['n_days']}) gaps {s['n_gaps']} "
              f"lead[min/med/max] {s['lead_h_min']}/{s['lead_h_median']}/{s['lead_h_max']}")
    return 0


def _render(out: dict) -> str:
    L = [f"# ECMWF daily-per-CP causal coverage audit (T-11-7) - **{out['verdict']}**", "",
         f"- Window {out['window'][0]}..{out['window'][1]}, every local date x 4 CPs. {out['note']}",
         f"- All CP coverage >= 0.99: {out['all_cp_coverage_ge_0_99']}; all selected runs causal: "
         f"{out['all_selected_runs_causal']}", "",
         "| CP | coverage | causal/days | gaps | lead_h min/median/max |",
         "|----|----------|-------------|------|------------------------|"]
    for cp, s in out["per_cp"].items():
        L.append(f"| {cp} | {s['coverage']} | {s['causal']}/{s['n_days']} | {s['n_gaps']} | "
                 f"{s['lead_h_min']}/{s['lead_h_median']}/{s['lead_h_max']} |")
    gaps = {cp: s["gaps_first5"] for cp, s in out["per_cp"].items() if s["n_gaps"]}
    if gaps:
        L += ["", "## Gaps (first 5 per CP)", ""] + [f"- {cp}: {g}" for cp, g in gaps.items()]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
