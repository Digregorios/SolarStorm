"""OFFLINE GFS S3 backfill -> canonical NWP snapshots (Phase 4 Option 1).

OFFLINE-ONLY (imports the eccodes-backed decoder). Pulls the causal GFS 18Z cycle
of day d-1 from AWS ``noaa-gfs-bdp-pds`` via .idx byte-range, decodes TMP:2m at the
NZWN gridpoint, and writes the canonical NWP schema under
``artifacts/raw/nwp/NZWN/ncep_gfs_global/s3_grib/`` so the existing causal selectors
(``select_nwp_ensemble`` / ``select_max_trajectory_anchor``) consume it unchanged.

WHY 18Z of d-1 + leads f000..f013: every CP in CP_SET {20,21,22,23} UTC for local
date d resolves (60-min safety margin) to the 18Z run of d-1 as the latest causal
cycle. The forward Tmax window (local 11-17h) and the backward trajectory [cp-5h,cp]
together span f000..~f012 of that run across both NZST and NZDT; f013 is margin.

TWO MODES (reviewer guardrail -- validate BEFORE bulk):
  --probe DATE : decode ONE run, print gridpoint lat/lon/distance + K->C range, and
                 compare against the on-disk HFAPI value at matching valid-times.
                 NOTHING is written. This is the gate the pre-registration update
                 depends on; only after it passes do we recompute the prereg sha256.
  (bulk)       : --start/--end loop, writes Parquet+SHA256 + a provenance sidecar.

The ~-1C cold bias is recorded in provenance, NEVER hand-corrected (the anchor enters
the residual as an anomaly; a manual nudge would be a hidden degree of freedom).
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from core.ingest.nwp import _write_partitioned
from core.ingest.nwp_client import NCEP_GFS

# Sibling-module import that works BOTH as ``py -3 -m scripts.gfs_s3_backfill``
# (package form) and ``py -3 scripts/gfs_s3_backfill.py`` (sys.path[0] == scripts/).
try:
    from scripts.gfs_grib_decode import (
        NZWN_LAT,
        NZWN_LON,
        DecodeProvenance,
        decode_tmp_2m_at_point,
        eccodes_version,
        fetch_tmp_2m_message,
    )
except ModuleNotFoundError:  # direct-script invocation: scripts/ is on sys.path
    from gfs_grib_decode import (
        NZWN_LAT,
        NZWN_LON,
        DecodeProvenance,
        decode_tmp_2m_at_point,
        eccodes_version,
        fetch_tmp_2m_message,
    )

REPO = Path(__file__).resolve().parents[1]
CAUSAL_RUN_HOUR = 18  # 18Z of d-1 is the latest causal cycle for all CP_SET hours
LEADS = tuple(range(0, 14))  # f000..f013
ENDPOINT = "s3_grib"
_SCHEMA = {
    "station": pl.Utf8,
    "model": pl.Utf8,
    "endpoint": pl.Utf8,
    "run_time_utc": pl.Datetime("us", time_zone="UTC"),
    "valid_time_utc": pl.Datetime("us", time_zone="UTC"),
    "lead_h": pl.Int32,
    "t2m_c": pl.Float64,
    "wind_speed_10m": pl.Float64,
    "wind_direction_10m": pl.Float64,
    "pressure_msl": pl.Float64,
    "cloud_cover": pl.Float64,
    "precipitation": pl.Float64,
}


def _decode_run(run_d: date, run_hour: int, prov: DecodeProvenance) -> list[dict]:
    """Decode TMP:2m at NZWN for one run across LEADS. Returns canonical rows.

    The network fetch (the dominant cost -- 2 GETs/lead to S3) is parallelized over
    LEADS; the eccodes decode + row/provenance assembly stay SERIAL in lead order so
    Parquet bytes are deterministic (protects the REQ-MOD-6 sha256 gate) and the
    eccodes handle is never touched concurrently.
    """
    run_dt = datetime(run_d.year, run_d.month, run_d.day, run_hour, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=min(len(LEADS), 8)) as ex:
        fetched = list(ex.map(lambda f: fetch_tmp_2m_message(run_d, run_hour, f), LEADS))
    rows: list[dict] = []
    for f, (data, rng) in zip(LEADS, fetched):
        t_c, glat, glon, dist = decode_tmp_2m_at_point(data, lat=NZWN_LAT, lon=NZWN_LON)
        if not prov.grid_lats:
            # The gridpoint is identical for every message (same nearest-cell on the
            # same grid), and only index [0] is read downstream -- record it once
            # instead of growing per-lead lists across the whole bulk.
            prov.grid_lats.append(glat)
            prov.grid_lons.append(glon)
            prov.distances_km.append(dist)
            prov.byte_ranges.append(rng)
        prov.n_messages += 1
        rows.append(
            {
                "station": "NZWN",
                "model": NCEP_GFS.id,
                "endpoint": ENDPOINT,
                "run_time_utc": run_dt,
                "valid_time_utc": run_dt + timedelta(hours=f),
                "lead_h": int(f),
                "t2m_c": float(t_c),
                "wind_speed_10m": None,
                "wind_direction_10m": None,
                "pressure_msl": None,
                "cloud_cover": None,
                "precipitation": None,
            }
        )
    return rows


def _probe(probe_date: date) -> int:
    """Decode the 18Z run of probe_date and report gridpoint + K->C sanity."""
    prov = DecodeProvenance(eccodes_version=eccodes_version())
    print(f"=== GFS GRIB probe: {probe_date} {CAUSAL_RUN_HOUR:02d}Z run ===")
    print(f"eccodes API version: {prov.eccodes_version}")
    print(f"requested gridpoint: lat={NZWN_LAT}, lon={NZWN_LON}")
    rows = _decode_run(probe_date, CAUSAL_RUN_HOUR, prov)
    t_vals = [r["t2m_c"] for r in rows]
    glat = prov.grid_lats[0]
    glon = prov.grid_lons[0]
    dist = prov.distances_km[0]
    print(f"returned gridpoint:  lat={glat:.4f}, lon={glon:.4f}  (distance={dist:.2f} km)")
    print(f"interpolation:       {prov.interpolation} (design.md: no regridding in v1)")
    print(f"TMP:2m K->C range:   min={min(t_vals):.2f}C max={max(t_vals):.2f}C "
          f"(expect ~6-17C for Wellington winter)")
    print(f"leads decoded:       f{LEADS[0]:03d}..f{LEADS[-1]:03d} ({len(rows)} messages)")
    print("")
    print("lead  valid_utc            t2m_c")
    for r in rows:
        print(f"  f{r['lead_h']:03d}  {r['valid_time_utc']:%Y-%m-%d %H:%M}  {r['t2m_c']:+.2f}")
    # HFAPI cross-sanity at matching valid-times (same gridpoint informativeness probe source)
    _compare_hfapi(probe_date, rows)
    sane = -10.0 <= min(t_vals) and max(t_vals) <= 40.0
    print("")
    print(f"K->C plausibility ([-10,40]C): {'PASS' if sane else 'FAIL'}")
    print(f"gridpoint distance < 20km:     {'PASS' if dist < 20 else 'FAIL'}")
    print("NOTE: cold bias is documented in provenance, NOT hand-corrected.")
    return 0 if sane else 1


def _compare_hfapi(run_d: date, rows: list[dict]) -> None:
    """Print GRIB vs HFAPI t2m at matching valid-times, if HFAPI is on disk."""
    target_y = (run_d + timedelta(days=1)).year
    target_m = (run_d + timedelta(days=1)).month
    hp = REPO / "artifacts" / "raw" / "nwp" / "NZWN" / NCEP_GFS.id / "hfapi" / f"{target_y:04d}" / f"{target_m:02d}.parquet"
    if not hp.exists():
        print(f"\n(no HFAPI partition at {hp.relative_to(REPO)}; skipping cross-sanity)")
        return
    hf = pl.read_parquet(hp).filter(pl.col("t2m_c").is_not_null())
    vt_to_hf = {r["valid_time_utc"]: r["t2m_c"] for r in hf.iter_rows(named=True)}
    print("\nGRIB vs HFAPI at matching valid-times (sanity; HFAPI is stitched/leaky):")
    print("  valid_utc            grib_c   hfapi_c  diff")
    for r in rows:
        h = vt_to_hf.get(r["valid_time_utc"])
        if h is None:
            continue
        print(f"  {r['valid_time_utc']:%Y-%m-%d %H:%M}  {r['t2m_c']:+6.2f}  {h:+6.2f}  {r['t2m_c']-h:+.2f}")


def _bulk(start: date, end: date, out_root: Path, sleep: float) -> int:
    """Decode the 18Z run of each day in [start-1, end-1] -> canonical Parquet.

    Rows are buffered and flushed ONE partition-write per run-month, not per run.
    ``_write_partitioned`` re-reads + merges each monthly partition, so a per-run
    flush is O(runs^2) within a month; buffering collapses it to O(runs) while
    bounding memory (~1 month of tiny TMP:2m rows) and crash-loss (at most the
    in-flight month). Failed runs are recorded (not just counted) so a transient
    S3 gap stays re-runnable rather than being silently dropped.
    """
    import time as _time

    prov = DecodeProvenance(eccodes_version=eccodes_version())
    # Runs: 18Z of (d-1) for each target local date d in [start, end].
    run_days = []
    cur = start - timedelta(days=1)
    last = end - timedelta(days=1)
    while cur <= last:
        run_days.append(cur)
        cur += timedelta(days=1)
    print(f"[bulk] {len(run_days)} runs ({CAUSAL_RUN_HOUR:02d}Z) x {len(LEADS)} leads "
          f"= {len(run_days)*len(LEADS)} byte-range GETs")
    n_ok = 0
    failed: list[str] = []
    buf: list[dict] = []
    buf_month: tuple[int, int] | None = None

    def _flush() -> None:
        if buf:
            _write_partitioned(
                pl.DataFrame(buf, schema=_SCHEMA),
                station="NZWN", model=NCEP_GFS, endpoint=ENDPOINT, out_root=out_root,
            )
            buf.clear()

    for i, rd in enumerate(run_days, 1):
        ym = (rd.year, rd.month)
        if buf_month is not None and ym != buf_month:
            _flush()  # close out the previous run-month in a single merge
        buf_month = ym
        try:
            rows = _decode_run(rd, CAUSAL_RUN_HOUR, prov)
        except Exception as exc:  # network/decode hiccup: record, continue (re-runnable)
            print(f"  [{i}/{len(run_days)}] {rd} {CAUSAL_RUN_HOUR:02d}Z ERROR: {exc}")
            failed.append(rd.isoformat())
            _time.sleep(sleep * 4)
            continue
        buf.extend(rows)
        n_ok += 1
        if i % 25 == 0 or i == len(run_days):
            print(f"  [{i}/{len(run_days)}] {rd} OK (cum_ok={n_ok})")
        _time.sleep(sleep)
    _flush()
    _write_provenance(out_root, prov, start, end, n_ok, failed)
    print(f"[bulk] done: {n_ok}/{len(run_days)} runs written")
    if failed:
        print(f"[bulk] {len(failed)} run(s) FAILED (re-runnable): {', '.join(failed)}")
    return 0


def _write_provenance(
    out_root: Path, prov: DecodeProvenance, start: date, end: date,
    n_ok: int, failed: list[str],
) -> None:
    """Write a provenance sidecar (reviewer guardrail: eccodes ver, gridpoint, interp, byte-ranges)."""
    p = out_root / "NZWN" / NCEP_GFS.id / ENDPOINT / "provenance.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    gl = prov.grid_lats or [None]
    payload = {
        "source": "AWS noaa-gfs-bdp-pds (anonymous HTTPS, .idx byte-range)",
        "variable": "TMP:2 m above ground",
        "eccodes_api_version": prov.eccodes_version,
        "interpolation": prov.interpolation,
        "regridding": "none (design.md v1: use provider gridpoint as-is)",
        "requested_lat": prov.requested_lat,
        "requested_lon": prov.requested_lon,
        "grid_lat": gl[0],
        "grid_lon": (prov.grid_lons or [None])[0],
        "grid_distance_km": (prov.distances_km or [None])[0],
        "kelvin_to_c": "t2m_c = TMP_kelvin - 273.15",
        "cold_bias_handling": "documented, NOT corrected (anchor enters as anomaly)",
        "causal_run_hour_utc": CAUSAL_RUN_HOUR,
        "leads_fhh": list(LEADS),
        "date_range": [start.isoformat(), end.isoformat()],
        "n_runs_written": n_ok,
        "n_runs_failed": len(failed),
        "failed_runs": failed,
        "n_messages_decoded": prov.n_messages,
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True), encoding="ascii")
    print(f"[prov] wrote {p.relative_to(out_root.parent if out_root.parent.exists() else out_root)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=str, default=None, help="single target date YYYY-MM-DD (validate only)")
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--out-root", type=str, default="artifacts/raw/nwp")
    ap.add_argument("--sleep", type=float, default=0.2)
    args = ap.parse_args()

    if args.probe:
        return _probe(date.fromisoformat(args.probe))
    if not (args.start and args.end):
        raise SystemExit("provide --probe DATE or both --start and --end")
    return _bulk(
        date.fromisoformat(args.start), date.fromisoformat(args.end),
        REPO / args.out_root, args.sleep,
    )


if __name__ == "__main__":
    raise SystemExit(main())
