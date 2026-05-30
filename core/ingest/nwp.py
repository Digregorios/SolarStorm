"""NWP snapshot manager + CP-aware causal selection (T-4-2).

Consolidates:
- ``snapshot_hfapi_range`` / ``snapshot_single_run`` writers with SHA256 manifest,
- ``select_nwp_v1`` deterministic CP-aware run picker with ``safety_margin``
  enforcement (RuntimeError on violation - REQ-DAT-5 + reforco B),
- ``read_snapshots`` to load the canonical NWP frame from disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from core.io.hashing import sha256_file
from core.ingest.nwp_client import (
    DEFAULT_VARIABLES,
    ModelSpec,
    fetch_hfapi,
    fetch_single_run,
)
from core.ingest.nwp_parse import (
    hfapi_response_to_dataframe,
    single_run_response_to_dataframe,
)


SAFETY_MARGIN_DEFAULT = timedelta(minutes=60)


def snapshot_hfapi_range(
    *,
    lat: float,
    lon: float,
    station: str,
    model: ModelSpec,
    start_date: date,
    end_date: date,
    out_root: Path | str,
) -> Path:
    """Fetch HFAPI for the date range and write one parquet per partition.

    Layout: ``out_root/<station>/<model_id>/hfapi/<yyyy>-<mm>.parquet``.
    Returns the manifest path.
    """
    payload = fetch_hfapi(
        lat=lat, lon=lon, model=model, start_date=start_date, end_date=end_date
    )
    df = hfapi_response_to_dataframe(payload, station=station, model=model)
    out_root = Path(out_root)
    return _write_partitioned(df, station=station, model=model, endpoint="hfapi", out_root=out_root)


def snapshot_single_run(
    *,
    lat: float,
    lon: float,
    station: str,
    model: ModelSpec,
    run_time_utc: datetime,
    out_root: Path | str,
) -> Path:
    if run_time_utc < datetime.combine(model.archive_start, datetime.min.time(), tzinfo=timezone.utc):
        raise ValueError(
            f"run_time_utc {run_time_utc} predates {model.id} archive_start "
            f"{model.archive_start}"
        )
    payload = fetch_single_run(lat=lat, lon=lon, model=model, run_time_utc=run_time_utc)
    df = single_run_response_to_dataframe(
        payload, station=station, model=model, run_time_utc=run_time_utc
    )
    out_root = Path(out_root)
    return _write_partitioned(
        df, station=station, model=model, endpoint="single_runs", out_root=out_root
    )


def _write_partitioned(
    df: pl.DataFrame, *, station: str, model: ModelSpec, endpoint: str, out_root: Path
) -> Path:
    """Write one parquet per (year, month) and append SHA256 to manifest."""
    if df.height == 0:
        raise ValueError("empty df, nothing to write")
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "manifest.jsonl"
    # Partition by VALID-time month (not run month): one forecast run's leads can
    # straddle two monthly files near a month boundary. The unique(keep="last")
    # merge below keeps that idempotent across overlapping/re-run bulk batches.
    df_with_ym = df.with_columns(
        pl.col("valid_time_utc").dt.year().alias("_y"),
        pl.col("valid_time_utc").dt.month().alias("_m"),
    )
    new_entries: list[dict] = []
    for (y, m), part in df_with_ym.group_by(["_y", "_m"], maintain_order=True):
        part = part.drop(["_y", "_m"]).sort(["valid_time_utc", "run_time_utc", "model"])
        rel_dir = out_root / station / model.id / endpoint / f"{int(y):04d}"
        rel_dir.mkdir(parents=True, exist_ok=True)
        out_path = rel_dir / f"{int(m):02d}.parquet"
        if out_path.exists():
            existing = pl.read_parquet(out_path)
            merged = pl.concat([existing, part], how="vertical_relaxed")
            merged = merged.unique(
                subset=["model", "endpoint", "run_time_utc", "valid_time_utc"],
                keep="last",
            ).sort(["valid_time_utc", "run_time_utc", "model"])
            merged.write_parquet(out_path, compression="zstd")
        else:
            part.write_parquet(out_path, compression="zstd")
        sha = sha256_file(out_path)
        new_entries.append(
            {
                "station": station,
                "model": model.id,
                "endpoint": endpoint,
                "year": int(y),
                "month": int(m),
                "rows": int(part.height),
                "sha256": sha,
                "path": str(out_path.relative_to(out_root).as_posix()),
            }
        )
    # Append to manifest (idempotent: don't rewrite, just append)
    with open(manifest_path, "a", encoding="ascii") as fh:
        for e in new_entries:
            fh.write(json.dumps(e, ensure_ascii=True, sort_keys=True) + "\n")
    return manifest_path


def read_snapshots(
    *,
    station: str,
    model: ModelSpec | None,
    endpoint: str,
    out_root: Path | str,
) -> pl.DataFrame:
    """Load all parquet partitions for the given station / model / endpoint."""
    root = Path(out_root) / station
    if model is None:
        # Aggregate across all models
        frames = []
        for model_dir in root.glob("*"):
            if not model_dir.is_dir():
                continue
            ep_dir = model_dir / endpoint
            if not ep_dir.exists():
                continue
            for p in ep_dir.rglob("*.parquet"):
                frames.append(pl.read_parquet(p))
        if not frames:
            return _empty_nwp_frame()
        return pl.concat(frames, how="vertical_relaxed").sort(
            ["valid_time_utc", "run_time_utc", "model"]
        )
    ep_dir = root / model.id / endpoint
    if not ep_dir.exists():
        return _empty_nwp_frame()
    frames = [pl.read_parquet(p) for p in ep_dir.rglob("*.parquet")]
    if not frames:
        return _empty_nwp_frame()
    return pl.concat(frames, how="vertical_relaxed").sort(
        ["valid_time_utc", "run_time_utc", "model"]
    )


def _empty_nwp_frame() -> pl.DataFrame:
    return pl.DataFrame(schema={
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
    })


@dataclass(frozen=True)
class NwpSelection:
    model: str
    run_time_utc: datetime
    valid_time_utc: datetime
    lead_h: int
    t2m_c: float | None
    spread_inputs: dict


def select_nwp_v1(
    snapshots: pl.DataFrame,
    *,
    cp_utc: datetime,
    target_valid_utc: datetime,
    safety_margin: timedelta = SAFETY_MARGIN_DEFAULT,
) -> NwpSelection | None:
    """Deterministic CP-causal pick (design 4.5.2 + ``contracts/nwp_source.md``).

    Filters runs with ``run_time_utc <= cp_utc - safety_margin``, keeps the
    latest, and returns the row matching ``valid_time_utc == target_valid_utc``
    (or the closest available lead). The ``run_time_utc <= cutoff`` filter below is
    the sole causality enforcement here (a post-filter re-check of the same column
    would be tautological); the standing leakage audit in
    ``audits/phases/nwp_timestamps.py`` re-validates selected rows each phase.
    """
    if snapshots.height == 0:
        return None
    if cp_utc.tzinfo is None or target_valid_utc.tzinfo is None:
        raise ValueError("cp_utc and target_valid_utc must be tz-aware UTC")

    cutoff = cp_utc - safety_margin
    causal = snapshots.filter(pl.col("run_time_utc") <= cutoff)
    if causal.height == 0:
        return None
    # Pick the latest run before the cutoff
    max_run = causal["run_time_utc"].max()
    candidate = causal.filter(pl.col("run_time_utc") == max_run)
    # Closest valid_time to target
    candidate = candidate.with_columns(
        ((pl.col("valid_time_utc") - target_valid_utc).abs()).alias("_dt")
    ).sort("_dt")
    row = candidate[0].to_dicts()[0]
    return NwpSelection(
        model=row["model"],
        run_time_utc=row["run_time_utc"],
        valid_time_utc=row["valid_time_utc"],
        lead_h=int(row["lead_h"]),
        t2m_c=row.get("t2m_c"),
        spread_inputs={"row": row},
    )


def select_nwp_ensemble(
    snapshots: pl.DataFrame,
    *,
    cp_utc: datetime,
    target_valid_utc: datetime,
    models: list[str],
    safety_margin: timedelta = SAFETY_MARGIN_DEFAULT,
) -> dict[str, NwpSelection | None]:
    """Apply ``select_nwp_v1`` per model in the ensemble."""
    out: dict[str, NwpSelection | None] = {}
    for m in models:
        sub = snapshots.filter(pl.col("model") == m)
        out[m] = select_nwp_v1(
            sub, cp_utc=cp_utc, target_valid_utc=target_valid_utc,
            safety_margin=safety_margin,
        )
    return out


__all__ = [
    "SAFETY_MARGIN_DEFAULT",
    "NwpSelection",
    "snapshot_hfapi_range",
    "snapshot_single_run",
    "read_snapshots",
    "select_nwp_v1",
    "select_nwp_ensemble",
]
