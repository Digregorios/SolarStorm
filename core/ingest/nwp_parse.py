"""NWP snapshots and CP-aware run selection (REQ-DAT-5, design 4.5.2).

Snapshots layout::

    artifacts/raw/nwp/<station>/<model_id>/<endpoint>/<yyyy>/<mm>/<dd>.parquet

Each row carries ``run_time_utc`` (issued time), ``valid_time_utc``, ``lead_h``,
``model``, ``endpoint`` and the variable values. The ``manifest.jsonl`` records
the SHA256 per partition.

Selection (design 4.5.2 + ``contracts/nwp_source.md``)::

    safety_margin = 60 min            # bumped from 30 default for Open-Meteo latency
    candidate_runs = { r : r.run_time_utc <= cp_utc - safety_margin }
    selected_run   = max(candidate_runs)
    target_valid   = climo_tmax_hour_local(date_local) -> UTC
    lead_h         = round_to_step((target_valid - selected_run).hours, model.cycle_h_lead_step)

Causality enforcement: any selection that violates ``run_time_utc <= cp - margin``
raises ``RuntimeError`` (REQ-DAT-5 + reforco B).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import polars as pl

from core.io.hashing import sha256_file
from core.ingest.nwp_client import (
    DEFAULT_VARIABLES,
    ModelSpec,
    fetch_hfapi,
    fetch_single_run,
    implied_run_time_hfapi,
)


@dataclass(frozen=True)
class NwpSnapshotRow:
    """One forecast row at a specific valid_time / lead."""

    station: str
    model: str
    endpoint: str
    run_time_utc: datetime
    valid_time_utc: datetime
    lead_h: int
    t2m_c: float | None
    wind_speed_10m: float | None
    wind_direction_10m: float | None
    pressure_msl: float | None
    cloud_cover: float | None
    precipitation: float | None


def _parse_iso_utc(s: str) -> datetime:
    """Open-Meteo returns ISO-8601 without tz suffix when timezone=UTC; coerce."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def hfapi_response_to_dataframe(
    payload: dict, *, station: str, model: ModelSpec, endpoint: str = "hfapi"
) -> pl.DataFrame:
    """Convert Open-Meteo HFAPI JSON into our canonical NWP snapshot frame.

    Annotates each row with the implied ``run_time_utc`` per the model's cycle.
    """
    hourly = payload.get("hourly")
    if hourly is None or "time" not in hourly:
        raise ValueError("HFAPI response missing 'hourly.time'")
    times = [_parse_iso_utc(s) for s in hourly["time"]]
    n = len(times)
    runs = [implied_run_time_hfapi(t, cycle_h=model.cycle_h) for t in times]
    leads = [int((v - r).total_seconds() // 3600) for v, r in zip(times, runs, strict=True)]

    def col(name: str) -> list[float | None]:
        v = hourly.get(name)
        if v is None:
            return [None] * n
        return [None if x is None else float(x) for x in v]

    return pl.DataFrame(
        {
            "station": [station] * n,
            "model": [model.id] * n,
            "endpoint": [endpoint] * n,
            "run_time_utc": runs,
            "valid_time_utc": times,
            "lead_h": leads,
            "t2m_c": col("temperature_2m"),
            "wind_speed_10m": col("wind_speed_10m"),
            "wind_direction_10m": col("wind_direction_10m"),
            "pressure_msl": col("pressure_msl"),
            "cloud_cover": col("cloud_cover"),
            "precipitation": col("precipitation"),
        },
        schema={
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
        },
    )


def single_run_response_to_dataframe(
    payload: dict, *, station: str, model: ModelSpec, run_time_utc: datetime
) -> pl.DataFrame:
    """Convert Single Runs response to canonical schema with explicit run_time."""
    hourly = payload.get("hourly")
    if hourly is None or "time" not in hourly:
        raise ValueError("Single Runs response missing 'hourly.time'")
    times = [_parse_iso_utc(s) for s in hourly["time"]]
    n = len(times)
    runs = [run_time_utc] * n
    leads = [int((v - run_time_utc).total_seconds() // 3600) for v in times]

    def col(name: str) -> list[float | None]:
        v = hourly.get(name)
        if v is None:
            return [None] * n
        return [None if x is None else float(x) for x in v]

    return pl.DataFrame(
        {
            "station": [station] * n,
            "model": [model.id] * n,
            "endpoint": ["single_runs"] * n,
            "run_time_utc": runs,
            "valid_time_utc": times,
            "lead_h": leads,
            "t2m_c": col("temperature_2m"),
            "wind_speed_10m": col("wind_speed_10m"),
            "wind_direction_10m": col("wind_direction_10m"),
            "pressure_msl": col("pressure_msl"),
            "cloud_cover": col("cloud_cover"),
            "precipitation": col("precipitation"),
        },
        schema={
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
        },
    )


__all__ = [
    "NwpSnapshotRow",
    "hfapi_response_to_dataframe",
    "single_run_response_to_dataframe",
]
