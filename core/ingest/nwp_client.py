"""Open-Meteo NWP HTTP clients (REQ-DAT-5, contracts/nwp_source.md v1.0).

Two endpoints:
- ``historical-forecast-api.open-meteo.com`` - stitched timeseries for backfill.
- ``single-runs-api.open-meteo.com`` - run-specific causal lookup (ECMWF since
  March 2024, others September 2025).

Hard rule (REQ-DAT-5 + reforco B): the resulting snapshots MUST carry
``run_time_utc`` (init time). Single Runs returns it natively; HFAPI returns
hourly stitched values, so we annotate them with the *implied* run_time per
Open-Meteo's documented stitching policy and validate against the model's
6-hourly cycle.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import httpx
import yaml


HFAPI_BASE = "https://historical-forecast-api.open-meteo.com/v1/forecast"
SINGLE_RUNS_BASE = "https://single-runs-api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class ModelSpec:
    """Identifier for an NWP model in our v1 set (contracts/nwp_source.md)."""

    id: str  # internal id (snake_case)
    open_meteo_id: str  # value of `models=` parameter in Open-Meteo URLs
    cycle_h: int  # hours between consecutive runs (6 for ECMWF/GFS)
    archive_start: date  # earliest run_time available


# v1 launch set per contracts/nwp_source.md.
# Open-Meteo URL parameters (verified empirically against the live API):
#   - "ecmwf_ifs"  -> ECMWF IFS HRES 9km (archive_start 2017-01-01)
#   - "gfs_global" -> NCEP GFS (archive_start 2021-03-23)
ECMWF_IFS_HRES = ModelSpec(
    id="ecmwf_ifs_hres",
    open_meteo_id="ecmwf_ifs",
    cycle_h=6,
    archive_start=date(2017, 1, 1),
)
NCEP_GFS = ModelSpec(
    id="ncep_gfs_global",
    open_meteo_id="gfs_global",
    cycle_h=6,
    archive_start=date(2021, 3, 23),
)
V1_MODELS: tuple[ModelSpec, ...] = (ECMWF_IFS_HRES, NCEP_GFS)

# Code is the source of truth for ModelSpec; the YAML is a mirror that MUST agree.
_MODELS_BY_ID: dict[str, ModelSpec] = {m.id: m for m in V1_MODELS}


class ConfigContractError(RuntimeError):
    """Raised when nzwn/config/model.yaml diverges from the code ModelSpec set.

    Dead/divergent config multiplies across phases as each phase reads new keys
    (review D4). We fail loudly at load time instead of letting the YAML rot.
    """


def load_nwp_model_specs(
    config_path: str | Path = "nzwn/config/model.yaml",
) -> tuple[ModelSpec, ...]:
    """Load ``nwp.models`` from model.yaml and ASSERT it matches the code ModelSpecs.

    Returns the code ``ModelSpec`` objects (the authoritative ones) in YAML order, but
    only after verifying every field the two sources share. Any mismatch -
    ``open_meteo_id``, ``cycle_h``, ``archive_start``, unknown/missing model id - raises
    ``ConfigContractError``. This is the config<->code contract test's runtime twin.
    """
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(f"Model config not found: {p}")
    with open(p, encoding="ascii") as fh:
        raw = yaml.safe_load(fh)
    nwp = (raw or {}).get("nwp", {})
    yaml_models = nwp.get("models", [])
    if not yaml_models:
        raise ConfigContractError("model.yaml has no nwp.models entries")

    out: list[ModelSpec] = []
    yaml_ids = [m.get("id") for m in yaml_models]
    for entry in yaml_models:
        mid = entry.get("id")
        spec = _MODELS_BY_ID.get(mid)
        if spec is None:
            raise ConfigContractError(
                f"model.yaml lists unknown nwp model id={mid!r}; "
                f"code knows {sorted(_MODELS_BY_ID)}"
            )
        mismatches: list[str] = []
        if entry.get("open_meteo_id") != spec.open_meteo_id:
            mismatches.append(
                f"open_meteo_id yaml={entry.get('open_meteo_id')!r} "
                f"code={spec.open_meteo_id!r}"
            )
        if int(entry.get("cycle_h", -1)) != spec.cycle_h:
            mismatches.append(
                f"cycle_h yaml={entry.get('cycle_h')!r} code={spec.cycle_h!r}"
            )
        yaml_archive = str(entry.get("archive_start", ""))
        if yaml_archive != spec.archive_start.isoformat():
            mismatches.append(
                f"archive_start yaml={yaml_archive!r} "
                f"code={spec.archive_start.isoformat()!r}"
            )
        if mismatches:
            raise ConfigContractError(
                f"model.yaml nwp model id={mid!r} diverges from code ModelSpec: "
                + "; ".join(mismatches)
            )
        out.append(spec)

    code_ids = {m.id for m in V1_MODELS}
    if set(yaml_ids) != code_ids:
        raise ConfigContractError(
            f"model.yaml nwp model set {sorted(yaml_ids)} != code V1 set {sorted(code_ids)}"
        )
    return tuple(out)

DEFAULT_VARIABLES: tuple[str, ...] = (
    "temperature_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "pressure_msl",
    "cloud_cover",
    "precipitation",
)


def _http_get(url: str, params: dict, *, timeout: float = 30.0, retries: int = 3) -> dict:
    """GET with retries; raises on persistent failure."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(url, params=params)
                r.raise_for_status()
                return r.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:  # type: ignore[misc]
            last_exc = exc
            time.sleep(1.0 * (2 ** attempt))
    raise RuntimeError(f"Open-Meteo GET failed after {retries} retries: {last_exc}") from last_exc


def fetch_hfapi(
    *,
    lat: float,
    lon: float,
    model: ModelSpec,
    start_date: date,
    end_date: date,
    variables: Iterable[str] = DEFAULT_VARIABLES,
    timezone_str: str = "UTC",
) -> dict:
    """Hit Open-Meteo Historical Forecast API for one model and a date range.

    Returns the parsed JSON. Caller is responsible for snapshot writing.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ",".join(variables),
        "models": model.open_meteo_id,
        "timezone": timezone_str,
        "timeformat": "iso8601",
    }
    return _http_get(HFAPI_BASE, params)


def fetch_single_run(
    *,
    lat: float,
    lon: float,
    model: ModelSpec,
    run_time_utc: datetime,
    variables: Iterable[str] = DEFAULT_VARIABLES,
) -> dict:
    """Hit Open-Meteo Single Runs API for one model at one initialization time."""
    if run_time_utc.tzinfo is None:
        raise ValueError("run_time_utc must be tz-aware UTC")
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": model.open_meteo_id,
        "run": run_time_utc.strftime("%Y-%m-%dT%H:%M"),
        "hourly": ",".join(variables),
        "timezone": "UTC",
        "timeformat": "iso8601",
    }
    return _http_get(SINGLE_RUNS_BASE, params)


def implied_run_time_hfapi(
    valid_time_utc: datetime, *, cycle_h: int = 6
) -> datetime:
    """For the HFAPI stitched timeseries, return the implied run_time_utc.

    Per Open-Meteo docs, valid_time T is sourced from the run with init at the
    most recent ``cycle_h`` boundary <= T. For 6-hourly cycles this is one of
    {00, 06, 12, 18} UTC. We return that boundary as a tz-aware UTC datetime.
    """
    if valid_time_utc.tzinfo is None:
        raise ValueError("valid_time_utc must be tz-aware UTC")
    if cycle_h <= 0 or 24 % cycle_h != 0:
        raise ValueError(f"cycle_h must divide 24; got {cycle_h}")
    h = (valid_time_utc.hour // cycle_h) * cycle_h
    return valid_time_utc.replace(hour=h, minute=0, second=0, microsecond=0)


__all__ = [
    "HFAPI_BASE",
    "SINGLE_RUNS_BASE",
    "ModelSpec",
    "ECMWF_IFS_HRES",
    "NCEP_GFS",
    "V1_MODELS",
    "DEFAULT_VARIABLES",
    "ConfigContractError",
    "load_nwp_model_specs",
    "fetch_hfapi",
    "fetch_single_run",
    "implied_run_time_hfapi",
]
