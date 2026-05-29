"""Deterministic METAR snapshots (REQ-DAT-1).

For each local date we write a CSV under ``artifacts/raw/metar/<station>/<yyyy>/<mm>/<dd>.csv``
plus a JSONL manifest line. Re-running with the same input must produce identical files
(idempotent).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from core.io.hashing import sha256_file
from core.io.timeutil import day_local_window


def snapshot_csv_by_local_day(
    df: pl.DataFrame,
    station: str,
    *,
    tz_name: str,
    out_root: Path | str,
    source_csv_sha256: str,
) -> dict[str, str]:
    """Partition ``df`` (must contain ``ts_utc`` UTC tz-aware) by local date and write CSVs.

    Returns a mapping ``{date_local_iso -> sha256}``.
    """
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "manifest.jsonl"

    if "ts_utc" not in df.columns:
        raise ValueError("df must have ts_utc.")
    df = df.with_columns(
        pl.col("ts_utc").dt.convert_time_zone(tz_name).dt.date().alias("date_local")
    ).sort(["date_local", "ts_utc"])

    hashes: dict[str, str] = {}
    distinct_dates = df["date_local"].unique().to_list()
    for d in distinct_dates:
        if d is None:
            continue
        sub = df.filter(pl.col("date_local") == d).drop("date_local")
        sub = sub.sort("ts_utc")
        rel_dir = out_root / station / f"{d.year:04d}" / f"{d.month:02d}"
        rel_dir.mkdir(parents=True, exist_ok=True)
        out_path = rel_dir / f"{d.day:02d}.csv"
        # Write CSV deterministically (sorted by ts_utc).
        sub.write_csv(out_path, include_header=True, line_terminator="\n")
        h = sha256_file(out_path)
        hashes[d.isoformat()] = h

    # Append manifest entries (idempotent: rewrite manifest from scratch sorted)
    entries = []
    for d_iso, h in sorted(hashes.items()):
        entries.append(
            {
                "station": station,
                "date_local": d_iso,
                "sha256": h,
                "source_csv_sha256": source_csv_sha256,
            }
        )
    with open(manifest_path, "w", encoding="ascii") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=True, sort_keys=True) + "\n")

    return hashes


def snapshot_path_for_date(
    out_root: Path | str, station: str, d: date
) -> Path:
    return Path(out_root) / station / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}.csv"


__all__ = ["snapshot_csv_by_local_day", "snapshot_path_for_date"]
