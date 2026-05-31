"""T-11-1 ECMWF causal-ingest PILOT backfill (small, controlled - per contracts feasibility GO).

Data-first: prove the path end-to-end on a small set of run_times across a CONTRASTING window
(autumn 2024-03 + winter 2024-07) before any full backfill. For each run: fetch ECMWF single-run,
write the snapshot (artifacts/raw/nwp, gitignored), and verify select_nwp_v1 picks a CAUSAL run at
the operational CP (run_time <= cp - safety_margin). Emit reports/nwp/ecmwf_backfill_pilot.md with a
GO/PAUSE verdict. No model change, no calibration, no execution.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from core.contracts.station import load_station_config
from core.ingest.nwp import read_snapshots, select_nwp_v1, snapshot_single_run
from core.ingest.nwp_client import ECMWF_IFS_HRES
from core.io.timeutil import cp_to_utc

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "artifacts" / "raw" / "nwp"
SAFETY = timedelta(minutes=60)
# Two contrasting CP target days (autumn + winter 2024). For EACH, fetch a DENSE run sequence:
# every 12h cycle across the 2 days BEFORE + the target day, so select_nwp_v1 has a local causal
# run to pick (a sparse sample would force the selector to reach across months - a pilot artifact).
TARGET_DAYS = [date(2024, 3, 16), date(2024, 7, 11)]
CYCLES_H = [0, 12]


def _run_times_for(target: date) -> list[datetime]:
    rts = []
    for back in (2, 1, 0):
        d = target - timedelta(days=back)
        for h in CYCLES_H:
            rts.append(datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc))
    return rts


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    written, fetch_errors = [], []
    all_rts = sorted({rt for t in TARGET_DAYS for rt in _run_times_for(t)})
    for rt in all_rts:
        try:
            p = snapshot_single_run(lat=cfg.lat, lon=cfg.lon, station="NZWN",
                                    model=ECMWF_IFS_HRES, run_time_utc=rt, out_root=OUT_ROOT)
            written.append((rt.isoformat(), str(p)))
        except Exception as exc:  # network/parse - record honestly
            fetch_errors.append((rt.isoformat(), f"{type(exc).__name__}: {exc}"))

    # Verify causal selection at CP23 for the pilot days (target valid = local Tmax-ish hour at CP).
    sel_rows = []
    try:
        snaps = read_snapshots(station="NZWN", model=ECMWF_IFS_HRES, endpoint="single_runs",
                               out_root=OUT_ROOT)
    except Exception as exc:
        snaps = pl.DataFrame()
        fetch_errors.append(("read_snapshots", f"{type(exc).__name__}: {exc}"))
    for d in TARGET_DAYS:
        cp_utc = cp_to_utc(d, "23:00")
        if snaps.height:
            sel = select_nwp_v1(snaps, cp_utc=cp_utc, target_valid_utc=cp_utc, safety_margin=SAFETY)
            if sel is not None:
                causal = sel.run_time_utc <= cp_utc - SAFETY
                sel_rows.append({"date": d.isoformat(), "cp_utc": cp_utc.isoformat(),
                                 "run_time_utc": sel.run_time_utc.isoformat(),
                                 "valid_time_utc": sel.valid_time_utc.isoformat(),
                                 "lead_h": sel.lead_h, "t2m_c": sel.t2m_c, "causal_ok": bool(causal)})
            else:
                sel_rows.append({"date": d.isoformat(), "cp_utc": cp_utc.isoformat(),
                                 "run_time_utc": None, "causal_ok": False})

    n_runs = len(all_rts)
    all_causal = bool(sel_rows) and all(r["causal_ok"] for r in sel_rows)
    downloads_clean = len(fetch_errors) == 0 and len(written) == n_runs
    coverage_ok = len(sel_rows) == len(TARGET_DAYS) and all(r.get("run_time_utc") for r in sel_rows)
    go = downloads_clean and all_causal and coverage_ok
    out = {
        "pilot": "ecmwf_causal_backfill", "model": "ecmwf_ifs_hres",
        "run_times_attempted": n_runs, "run_times_written": len(written),
        "fetch_errors": fetch_errors, "selection": sel_rows,
        "gate": {"downloads_clean": downloads_clean, "all_causal_at_cp23": all_causal,
                 "cp_coverage_ok": coverage_ok},
        "verdict": "GO" if go else "PAUSE",
        "next_action": ("Full backfill ECMWF single-runs 2024-03..2025-12 (~2680 calls, ~22 partitions); "
                        "accept split-1 asymmetry (ECMWF only for dates >= 2024-03); run T-OPN-5a cross-check "
                        "before promoting." if go else
                        "PAUSE: resolve the failing gate item before any full backfill."),
        "note": "Pilot only; no model/calibration/execution change. Snapshots in artifacts/raw/nwp (gitignored).",
    }
    rep = REPO / "reports" / "nwp"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "ecmwf_backfill_pilot.json").write_text(
        json.dumps(out, ensure_ascii=True, sort_keys=True, indent=2, default=str), encoding="ascii")
    (rep / "ecmwf_backfill_pilot.md").write_text(_render(out), encoding="ascii")
    print(f"VERDICT {out['verdict']} | written {len(written)}/{n_runs} | causal_at_cp23 {all_causal} "
          f"| errors {len(fetch_errors)}")
    for r in sel_rows:
        print(f"  {r['date']}: run {r.get('run_time_utc')} lead {r.get('lead_h')} causal {r['causal_ok']}")
    return 0


def _render(out: dict) -> str:
    L = [f"# ECMWF causal-ingest PILOT backfill (T-11-1) - **{out['verdict']}**", "",
         f"- Model `{out['model']}`; run_times {out['run_times_written']}/{out['run_times_attempted']} written. {out['note']}",
         f"- Gate: {out['gate']}", f"- Next: {out['next_action']}", "",
         "## Causal selection at CP23 (run_time <= cp - 60min)", "",
         "| date | cp_utc | run_time_utc | valid_time_utc | lead_h | t2m_c | causal |",
         "|------|--------|--------------|----------------|--------|-------|--------|"]
    for r in out["selection"]:
        L.append(f"| {r['date']} | {r['cp_utc']} | {r.get('run_time_utc')} | {r.get('valid_time_utc')} | "
                 f"{r.get('lead_h')} | {r.get('t2m_c')} | {r['causal_ok']} |")
    if out["fetch_errors"]:
        L += ["", "## Fetch errors", ""] + [f"- {rt}: {e}" for rt, e in out["fetch_errors"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
