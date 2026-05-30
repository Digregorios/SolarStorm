"""NWP backfill (T-4-2 operational invocation).

Pulls Open-Meteo Historical Forecast API for ECMWF IFS HRES and NCEP GFS over
2020-01-01..2026-05-27 at NZWN coordinates and writes parquet snapshots under
``artifacts/raw/nwp/``.

Usage::

    py -3 scripts\\nwp_backfill.py --start 2023-01-01 --end 2023-12-31 --models ecmwf gfs

Strategy: chunk by ~2-week windows to stay under Open-Meteo's per-call cost
(>10 vars or >2 weeks counts as multiple calls).
"""

from __future__ import annotations

import argparse
import time
from datetime import date, timedelta
from pathlib import Path

from core.contracts.station import load_station_config
from core.ingest.nwp import snapshot_hfapi_range
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS, ModelSpec
from core.io.logging import log_event, new_run_id


REPO = Path(__file__).resolve().parents[1]
CHUNK_DAYS = 14


def _chunks(start: date, end: date, span: int) -> list[tuple[date, date]]:
    out = []
    cur = start
    while cur <= end:
        nxt = min(end, cur + timedelta(days=span - 1))
        out.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=str, default="2023-01-01")
    ap.add_argument("--end", type=str, default="2026-05-27")
    ap.add_argument("--models", nargs="+", default=["ecmwf", "gfs"])
    ap.add_argument("--out-root", type=str, default="artifacts/raw/nwp")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    new_run_id()
    out_root = REPO / args.out_root

    model_map: dict[str, ModelSpec] = {
        "ecmwf": ECMWF_IFS_HRES,
        "gfs": NCEP_GFS,
    }
    selected = [model_map[m] for m in args.models if m in model_map]
    if not selected:
        raise SystemExit(f"No valid models in {args.models}")
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    chunks = _chunks(start, end, CHUNK_DAYS)
    print(f"Backfill {start}..{end}: {len(chunks)} chunks x {len(selected)} models = {len(chunks) * len(selected)} calls")

    for model in selected:
        # Clip chunks to the model's archive_start
        eff_start = max(start, model.archive_start)
        if eff_start > end:
            print(f"  {model.id}: archive_start={model.archive_start} > end={end}; skip")
            continue
        chs = _chunks(eff_start, end, CHUNK_DAYS)
        print(f"  {model.id}: {len(chs)} chunks (eff_start={eff_start})")
        for i, (s, e) in enumerate(chs, 1):
            log_event(
                "nwp_backfill", "chunk.start",
                extra={"model": model.id, "start": s.isoformat(), "end": e.isoformat(),
                       "i": i, "n": len(chs)},
            )
            try:
                snapshot_hfapi_range(
                    lat=cfg.lat, lon=cfg.lon, station=cfg.icao,
                    model=model, start_date=s, end_date=e, out_root=out_root,
                )
            except Exception as exc:
                log_event("nwp_backfill", "chunk.error", level="ERROR",
                          extra={"model": model.id, "error": str(exc),
                                 "start": s.isoformat(), "end": e.isoformat()})
                print(f"    [{i}/{len(chs)}] {model.id} {s}..{e} ERROR: {exc}")
                time.sleep(args.sleep * 4)
                continue
            print(f"    [{i}/{len(chs)}] {model.id} {s}..{e} OK")
            time.sleep(args.sleep)

    print("[done] backfill complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
