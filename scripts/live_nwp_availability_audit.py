"""Onda 2-A live NWP availability audit (read-only, no fetch, no model).

For every local date in the window x every CP (20/21/22/23), check whether
``select_nwp_v1`` returns a CAUSAL run (``run_time <= cp - 60min``) for EACH
model, using the canonical per-model endpoints (ECMWF -> single_runs, GFS ->
s3_grib; from ``ENDPOINT_BY_MODEL`` so the audit can never drift from the live
probe). Reports per model/CP: causal coverage, fallback rate, lead_h and
run_time-age distributions, and missing month buckets; plus an ``any_causal``
row (covered if EITHER model is causal -- what the router keys off at CP20-22).

Descriptive only: the verdict tests a pre-stated >=0.99 any_causal coverage
threshold (frozen in the report text before the numbers). No model is selected
or tuned; causality is delegated unchanged to ``select_nwp_v1``.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

from core.contracts.station import load_station_config
from core.ingest.nwp import SAFETY_MARGIN_DEFAULT, read_snapshots, select_nwp_v1
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.ingest.nwp_live import ENDPOINT_BY_MODEL
from core.io.timeutil import cp_to_utc

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "artifacts" / "raw" / "nwp"
STATION = "NZWN"
CP_SET = ["20:00", "21:00", "22:00", "23:00"]
SAFETY = SAFETY_MARGIN_DEFAULT
START, END = date(2021, 1, 1), date(2025, 12, 31)
COVERAGE_THRESHOLD = 0.99  # frozen BEFORE the numbers (anti-gaming)

# (label, ModelSpec, endpoint) -- endpoints from the shared map, never hardcoded here.
MODELS = [
    ("ecmwf", ECMWF_IFS_HRES, ENDPOINT_BY_MODEL[ECMWF_IFS_HRES.id]),
    ("gfs", NCEP_GFS, ENDPOINT_BY_MODEL[NCEP_GFS.id]),
]


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _dates(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def _summ(values: list[float]) -> dict:
    """min/median/max of a list (0s when empty)."""
    arr = np.array(values, dtype=float) if values else np.array([0.0])
    return {
        "min": float(arr.min()),
        "median": float(np.median(arr)),
        "max": float(arr.max()),
    }


def audit_model(
    snaps: pl.DataFrame,
    *,
    cp_set: list[str],
    dates: list[date],
    safety: timedelta,
) -> dict:
    """Pure per-model accumulation over a date x CP grid.

    Returns ``{cp: raw_block}`` where each block holds the counters needed by
    ``summarize`` (n, causal, leads, run_age_h, gaps, months_seen). ``snaps`` is
    a single model's snapshot frame (possibly empty); causality and selection are
    delegated to ``select_nwp_v1`` unchanged.
    """
    per_cp: dict[str, dict] = {
        cp: {"n": 0, "causal": 0, "leads": [], "run_age_h": [], "gaps": [], "months_causal": set()}
        for cp in cp_set
    }
    for d in dates:
        for cp in cp_set:
            block = per_cp[cp]
            block["n"] += 1
            cp_utc = cp_to_utc(d, cp)
            sel = select_nwp_v1(
                snaps, cp_utc=cp_utc, target_valid_utc=cp_utc, safety_margin=safety
            )
            causal = (
                sel is not None
                and sel.t2m_c is not None
                and sel.run_time_utc <= cp_utc - safety
            )
            if causal:
                block["causal"] += 1
                block["leads"].append(int(sel.lead_h))
                block["run_age_h"].append((cp_utc - sel.run_time_utc).total_seconds() / 3600.0)
                block["months_causal"].add((d.year, d.month))
            else:
                block["gaps"].append(d.isoformat())
    return per_cp


def _months_in_window(dates: list[date]) -> set[tuple[int, int]]:
    return {(d.year, d.month) for d in dates}


def summarize(per_cp: dict, *, all_months: set[tuple[int, int]]) -> dict:
    """Derive coverage / fallback_rate / lead / run_age / missing-month metrics."""
    out: dict = {}
    for cp, v in per_cp.items():
        n = v["n"]
        cov = round(v["causal"] / n, 4) if n else 0.0
        missing_months = sorted(all_months - v["months_causal"])
        out[cp] = {
            "n_days": n,
            "causal": v["causal"],
            "coverage": cov,
            "fallback_rate": round(1.0 - cov, 4),
            "n_gaps": len(v["gaps"]),
            "gaps_first5": v["gaps"][:5],
            "lead_h": _summ(v["leads"]),
            "run_age_h": _summ(v["run_age_h"]),
            "n_missing_months": len(missing_months),
            "missing_months_first5": [f"{y:04d}-{m:02d}" for y, m in missing_months[:5]],
        }
    return out


def _any_causal(per_model_raw: dict[str, dict], *, cp_set: list[str], n_days: int) -> dict:
    """Per-CP coverage where a day counts as covered if ANY model is causal.

    Derives from the per-model gap sets: a (cp, day) is covered iff it is NOT a
    gap for every model.
    """
    out: dict = {}
    for cp in cp_set:
        gap_sets = [set(per_model_raw[label][cp]["gaps"]) for label in per_model_raw]
        common_gaps = set.intersection(*gap_sets) if gap_sets else set()
        causal = n_days - len(common_gaps)
        cov = round(causal / n_days, 4) if n_days else 0.0
        out[cp] = {
            "n_days": n_days,
            "causal": causal,
            "coverage": cov,
            "fallback_rate": round(1.0 - cov, 4),
            "n_gaps": len(common_gaps),
            "gaps_first5": sorted(common_gaps)[:5],
        }
    return out


def main() -> int:
    load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    dates = _dates(START, END)
    all_months = _months_in_window(dates)

    per_model_raw: dict[str, dict] = {}
    per_model_summary: dict[str, dict] = {}
    endpoints: dict[str, str] = {}
    for label, spec, endpoint in MODELS:
        endpoints[label] = endpoint
        snaps = read_snapshots(
            station=STATION, model=spec, endpoint=endpoint, out_root=OUT_ROOT
        )
        raw = audit_model(snaps, cp_set=CP_SET, dates=dates, safety=SAFETY)
        per_model_raw[label] = raw
        per_model_summary[label] = summarize(raw, all_months=all_months)

    any_causal = _any_causal(per_model_raw, cp_set=CP_SET, n_days=len(dates))
    all_any_full = all(s["coverage"] >= COVERAGE_THRESHOLD for s in any_causal.values())
    offending = [cp for cp, s in any_causal.items() if s["coverage"] < COVERAGE_THRESHOLD]

    out = {
        "audit": "live_nwp_availability",
        "git_sha": _git_sha(),
        "station": STATION,
        "window": [START.isoformat(), END.isoformat()],
        "safety_margin_min": int(SAFETY.total_seconds() // 60),
        "coverage_threshold": COVERAGE_THRESHOLD,
        "endpoints": endpoints,
        "per_model": per_model_summary,
        "any_causal": any_causal,
        "verdict": "GO" if all_any_full else "PAUSE",
        "offending_cps": offending,
        "note": (
            "Read-only causal audit over local snapshots; no fetch, no model. "
            "run_time <= cp - 60min enforced by select_nwp_v1 and re-checked here. "
            "Per-model endpoints from ENDPOINT_BY_MODEL (ecmwf single_runs, gfs s3_grib). "
            f"Verdict threshold any_causal coverage >= {COVERAGE_THRESHOLD} on all CPs "
            "was frozen before the numbers. ECMWF pre-2024 absence is reported honestly "
            "as a per-CP coverage gap, not a bug -- the audit measures reality."
        ),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }

    rep = REPO / "reports" / "live_nwp"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "availability_audit.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str),
        encoding="ascii",
    )
    (rep / "availability_audit.md").write_text(_render(out), encoding="ascii")

    print(f"VERDICT {out['verdict']} | any_causal>=thr {all_any_full} | offending {offending or '-'}")
    for label in per_model_summary:
        print(f"  [{label} @ {endpoints[label]}]")
        for cp, s in per_model_summary[label].items():
            print(
                f"    {cp}: cov {s['coverage']} ({s['causal']}/{s['n_days']}) "
                f"fb {s['fallback_rate']} miss_months {s['n_missing_months']} "
                f"lead[min/med/max] {s['lead_h']['min']}/{s['lead_h']['median']}/{s['lead_h']['max']}"
            )
    for cp, s in any_causal.items():
        print(f"  any[{cp}]: cov {s['coverage']} ({s['causal']}/{s['n_days']}) fb {s['fallback_rate']}")
    return 0


def _render(out: dict) -> str:
    L = [
        f"# Live NWP availability audit (Onda 2-A) - **{out['verdict']}**",
        "",
        f"- git_sha: `{out['git_sha']}`  station: {out['station']}  "
        f"window: {out['window'][0]}..{out['window'][1]}  safety: {out['safety_margin_min']}min",
        f"- {out['note']}",
        "",
        "## any_causal (router keys off EITHER model at CP20-22)",
        "",
        "| CP | coverage | causal/days | fallback_rate | n_gaps |",
        "|----|----------|-------------|---------------|--------|",
    ]
    for cp, s in out["any_causal"].items():
        L.append(
            f"| {cp} | {s['coverage']} | {s['causal']}/{s['n_days']} | "
            f"{s['fallback_rate']} | {s['n_gaps']} |"
        )
    if out["offending_cps"]:
        L += ["", f"_PAUSE: any_causal coverage < {out['coverage_threshold']} at CPs "
              f"{out['offending_cps']}._"]
    for label, summary in out["per_model"].items():
        L += [
            "",
            f"## {label} (endpoint: {out['endpoints'][label]})",
            "",
            "| CP | coverage | causal/days | fallback_rate | lead min/med/max | "
            "run_age_h min/med/max | n_missing_months |",
            "|----|----------|-------------|---------------|------------------|"
            "-----------------------|------------------|",
        ]
        for cp, s in summary.items():
            lead = s["lead_h"]
            age = s["run_age_h"]
            L.append(
                f"| {cp} | {s['coverage']} | {s['causal']}/{s['n_days']} | "
                f"{s['fallback_rate']} | {lead['min']}/{lead['median']}/{lead['max']} | "
                f"{age['min']}/{age['median']}/{age['max']} | {s['n_missing_months']} |"
            )
    gaps = {
        label: {cp: s["missing_months_first5"] for cp, s in summary.items() if s["n_missing_months"]}
        for label, summary in out["per_model"].items()
    }
    gaps = {k: v for k, v in gaps.items() if v}
    if gaps:
        L += ["", "## Missing months (first 5 per model/CP)", ""]
        for label, cps in gaps.items():
            for cp, months in cps.items():
                L.append(f"- {label} {cp}: {months}")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
