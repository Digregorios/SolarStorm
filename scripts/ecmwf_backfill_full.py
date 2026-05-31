"""T-11-4 ECMWF full backfill (controlled, idempotent, resumable).

Causal ECMWF single-runs for 2024-03-01..2025-12-31, cycles 00Z + 12Z. Idempotent (skip if the
snapshot partition already exists), rate-limited with retry/backoff, capped per invocation
(--max-runs) so a single run never times out - re-invoke to resume. NO model, NO calibration, NO
execution; data + causal/coverage audit only.

Usage: py -3 scripts/ecmwf_backfill_full.py [--max-runs N]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core.contracts.station import load_station_config
from core.ingest.nwp import read_snapshots, select_nwp_v1, snapshot_single_run
from core.ingest.nwp_client import ECMWF_IFS_HRES
from core.io.timeutil import cp_to_utc

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "artifacts" / "raw" / "nwp"
START, END = date(2024, 3, 1), date(2025, 12, 31)
CYCLES_H = [0, 12]
SAFETY = timedelta(minutes=60)
CP_SET = ["20:00", "21:00", "22:00", "23:00"]


def _all_run_times() -> list[datetime]:
    rts, d = [], START
    while d <= END:
        for h in CYCLES_H:
            rts.append(datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc))
        d += timedelta(days=1)
    return rts


def _existing_run_times(station: str) -> set[datetime]:
    snaps = read_snapshots(station=station, model=ECMWF_IFS_HRES, endpoint="single_runs",
                           out_root=OUT_ROOT)
    if snaps.height == 0:
        return set()
    return set(snaps["run_time_utc"].unique().to_list())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-runs", type=int, default=400)
    args = ap.parse_args()
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")

    have = _existing_run_times("NZWN")
    todo = [rt for rt in _all_run_times() if rt not in have]
    chunk = todo[: args.max_runs]
    downloaded, failed = [], []
    for rt in chunk:
        for attempt in range(3):
            try:
                snapshot_single_run(lat=cfg.lat, lon=cfg.lon, station="NZWN",
                                    model=ECMWF_IFS_HRES, run_time_utc=rt, out_root=OUT_ROOT)
                downloaded.append(rt.isoformat())
                break
            except Exception as exc:  # network/parse - retry then record
                if attempt == 2:
                    failed.append((rt.isoformat(), f"{type(exc).__name__}: {exc}"))
                else:
                    time.sleep(2.0 * (attempt + 1))
        time.sleep(0.25)

    _audit(cfg, len(have), len(todo), downloaded, failed)
    print(f"downloaded {len(downloaded)} failed {len(failed)} remaining "
          f"{len(todo) - len(downloaded)} (had {len(have)})")
    return 0


def _audit(cfg, n_had, n_todo_before, downloaded, failed) -> None:
    expected = len(_all_run_times())
    have_after = _existing_run_times("NZWN")
    # Coverage + causal audit: sample one local date per month, check a causal run exists per CP.
    snaps = read_snapshots(station="NZWN", model=ECMWF_IFS_HRES, endpoint="single_runs",
                           out_root=OUT_ROOT)
    cov, d = [], START
    months_seen = set()
    while d <= END:
        key = (d.year, d.month)
        if key not in months_seen and snaps.height:
            months_seen.add(key)
            probe = date(d.year, d.month, 15)
            per_cp = {}
            for cp in CP_SET:
                cp_utc = cp_to_utc(probe, cp)
                sel = select_nwp_v1(snaps, cp_utc=cp_utc, target_valid_utc=cp_utc, safety_margin=SAFETY)
                per_cp[cp] = bool(sel is not None and sel.run_time_utc <= cp_utc - SAFETY)
            cov.append({"month": f"{d.year}-{d.month:02d}", "causal_per_cp": per_cp})
        d += timedelta(days=1)

    n_have = len(have_after)
    complete = n_have >= expected
    pct = round(100.0 * n_have / expected, 1) if expected else 0.0
    all_months_causal = all(all(m["causal_per_cp"].values()) for m in cov) if cov else False
    out = {
        "backfill": "ecmwf_full", "window": [START.isoformat(), END.isoformat()],
        "expected_runs": expected, "have_runs": n_have, "pct_complete": pct,
        "downloaded_this_run": len(downloaded), "failed_this_run": failed,
        "remaining": max(0, expected - n_have), "complete": complete,
        "coverage_audit_sampled_months": cov,
        "all_sampled_months_causal_all_cp": all_months_causal,
        "verdict": ("GO" if (complete or pct >= 95.0) and all_months_causal and not failed
                    else ("IN_PROGRESS" if not complete else "PAUSE")),
        "note": "Idempotent/resumable: re-run to continue. Data + causal/coverage audit only; no model. "
                "Snapshots in artifacts/raw/nwp (gitignored).",
    }
    rep = REPO / "reports" / "nwp"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "ecmwf_backfill_full.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    (rep / "ecmwf_backfill_full.md").write_text(_render(out), encoding="ascii")


def _render(out: dict) -> str:
    L = [f"# ECMWF full backfill (T-11-4) - **{out['verdict']}**", "",
         f"- Window {out['window'][0]}..{out['window'][1]}; cycles 00Z/12Z. {out['note']}",
         f"- Runs: {out['have_runs']}/{out['expected_runs']} ({out['pct_complete']}%); "
         f"downloaded this run {out['downloaded_this_run']}; remaining {out['remaining']}; "
         f"failed this run {len(out['failed_this_run'])}.",
         f"- All sampled months causal at every CP: {out['all_sampled_months_causal_all_cp']}", "",
         "## Causal coverage audit (one probe day per month; run_time <= cp-60min)", "",
         "| month | 20Z | 21Z | 22Z | 23Z |", "|-------|-----|-----|-----|-----|"]
    for m in out["coverage_audit_sampled_months"]:
        c = m["causal_per_cp"]
        L.append(f"| {m['month']} | {c['20:00']} | {c['21:00']} | {c['22:00']} | {c['23:00']} |")
    if out["failed_this_run"]:
        L += ["", "## Failures this run", ""] + [f"- {rt}: {e}" for rt, e in out["failed_this_run"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
