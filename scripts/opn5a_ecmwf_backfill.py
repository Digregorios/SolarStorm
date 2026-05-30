"""OFFLINE ECMWF Single Runs backfill for the T-OPN-5a cross-check (Phase 4).

ECMWF causal single-runs exist on Open-Meteo only from 2024-03 (verified empirically:
Feb 2024 = 0 non-null t2m, Mar 2024 = full grid). With Option 1 (GFS as the homogeneous
anchor), ECMWF here is NOT the anchor -- it is the OUT-OF-MODEL cross-check / diagnostic
ceiling (the informativeness probe put ECMWF at pearson 0.97 vs GFS 0.95). Comparing the
GFS-anchored result against ECMWF corroborates that the result is not a single-model
artifact (reviewer guardrail).

Pulls the 18Z run of d-1 (the same causal cycle the GFS anchor uses, so the
max-of-trajectory aggregation is comparable) for each target date in the overlap window
2024-03-01..2025-12-31, writing canonical Single Runs snapshots via the existing,
tested ``snapshot_single_run`` (network: single-runs-api.open-meteo.com).
"""

from __future__ import annotations

import argparse
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core.contracts.station import load_station_config
from core.ingest.nwp import snapshot_single_run
from core.ingest.nwp_client import ECMWF_IFS_HRES
from core.io.logging import log_event, new_run_id

REPO = Path(__file__).resolve().parents[1]
CAUSAL_RUN_HOUR = 18  # 18Z of d-1: the causal cycle for CP_SET {20,21,22,23} UTC


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=str, default="2024-03-01", help="first TARGET local date")
    ap.add_argument("--end", type=str, default="2025-12-31", help="last TARGET local date")
    ap.add_argument("--out-root", type=str, default="artifacts/raw/nwp")
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    new_run_id()
    out_root = REPO / args.out_root
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    # Runs are the 18Z cycle of (target_date - 1).
    run_days: list[date] = []
    cur = start - timedelta(days=1)
    last = end - timedelta(days=1)
    while cur <= last:
        run_days.append(cur)
        cur += timedelta(days=1)
    print(f"ECMWF Single Runs backfill: {len(run_days)} runs ({CAUSAL_RUN_HOUR:02d}Z) "
          f"for targets {start}..{end}")

    n_ok = 0
    for i, rd in enumerate(run_days, 1):
        run_dt = datetime(rd.year, rd.month, rd.day, CAUSAL_RUN_HOUR, tzinfo=timezone.utc)
        try:
            snapshot_single_run(
                lat=cfg.lat, lon=cfg.lon, station=cfg.icao,
                model=ECMWF_IFS_HRES, run_time_utc=run_dt, out_root=out_root,
            )
        except Exception as exc:
            log_event("opn5a_ecmwf_backfill", "run.error", level="ERROR",
                      extra={"run": run_dt.isoformat(), "error": str(exc)})
            print(f"  [{i}/{len(run_days)}] {run_dt:%Y-%m-%d}Z ERROR: {exc}")
            time.sleep(args.sleep * 4)
            continue
        n_ok += 1
        if i % 25 == 0 or i == len(run_days):
            print(f"  [{i}/{len(run_days)}] {rd} OK (cum_ok={n_ok})")
        time.sleep(args.sleep)

    print(f"[done] ECMWF Single Runs backfill: {n_ok}/{len(run_days)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
