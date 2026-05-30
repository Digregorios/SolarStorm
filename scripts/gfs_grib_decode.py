"""OFFLINE GFS GRIB2 decode -> canonical NWP snapshot (Phase 4 Option 1).

THIS MODULE IS OFFLINE-ONLY. It imports ``eccodes`` and must NEVER be imported by
anything under ``core/`` that the deterministic runtime or CI touches (REQ-MOD-6:
two trainings must be byte-identical; eccodes on the import graph risks that). The
ingestion path is: decode here -> write Parquet+SHA256+provenance -> the
deterministic pipeline reads only Parquet. ``core/ingest/grib_idx.py`` (eccodes-free)
holds the byte-range logic and IS unit-tested in CI.

Pipeline (reviewer guardrails, update.txt):
  1. CAUSAL single-run selection from S3 -- pick the GFS cycle whose run_time_utc
     <= cp_utc - safety_margin (done by the caller / backfill script, not here).
  2. Byte-range fetch of ONLY the TMP:2m message via the .idx (no full-field pull).
  3. Decode with eccodes; extract the SAME gridpoint as the HFAPI probe by
     nearest-cell (design.md: NO regridding in v1) at lat=-41.3272, lon=174.8053.
  4. K->C conversion (NEW bug surface: HFAPI was already C, GRIB2 TMP is native
     Kelvin). Spot-check range 6-17C for June Wellington at call sites.
  5. Provenance recorded: eccodes version, byte range, gridpoint lat/lon actually
     returned, interpolation rule. Cold bias (~-1C) is documented, NOT hand-corrected
     (it is absorbed as the anchor enters as an anomaly / the residual learns it).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from core.ingest.grib_idx import (
    byte_range_header,
    find_tmp_2m,
    gfs_grib_url,
    gfs_idx_url,
    parse_idx,
)

# NZWN gridpoint -- MUST match the point used by the HFAPI informativeness probe,
# else the measured informativeness (pearson ~0.95) does not transfer.
NZWN_LAT = -41.3272
NZWN_LON = 174.8053
KELVIN_0C = 273.15


@dataclass(frozen=True)
class GfsPoint:
    """One decoded TMP:2m value at the NZWN gridpoint with provenance."""

    run_time_utc: datetime
    valid_time_utc: datetime
    lead_h: int
    t2m_c: float
    grid_lat: float  # actual gridpoint lat eccodes returned (nearest-cell)
    grid_lon: float
    distance_km: float
    eccodes_version: str
    byte_range: str


@dataclass
class DecodeProvenance:
    """Aggregated provenance for a decode run (written alongside Parquet)."""

    eccodes_version: str = ""
    interpolation: str = "nearest_cell"
    requested_lat: float = NZWN_LAT
    requested_lon: float = NZWN_LON
    grid_lats: list[float] = field(default_factory=list)
    grid_lons: list[float] = field(default_factory=list)
    distances_km: list[float] = field(default_factory=list)
    byte_ranges: list[str] = field(default_factory=list)
    n_messages: int = 0


# Single pooled client reused across ALL requests. Each TMP:2m pull needs 2 GETs
# (.idx + byte-range) and a year is ~365 runs x 14 leads, so a fresh client per call
# meant ~10k TLS handshakes to S3. Keep-alive to the single S3 host amortizes that to
# one handshake -- the dominant cost, since each message is only a few hundred KB.
_CLIENT: httpx.Client | None = None


def _client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(
            timeout=60.0,
            follow_redirects=True,
            limits=httpx.Limits(
                max_keepalive_connections=8, max_connections=8, keepalive_expiry=120.0
            ),
        )
    return _CLIENT


_MAX_RETRIES = 3  # mirror nwp_client._http_get: transient S3 hiccups over ~10k GETs/yr


def _get_with_retry(url: str, headers: dict[str, str] | None) -> httpx.Response:
    """GET via the pooled client with bounded exponential backoff on TRANSIENT
    errors (5xx / 429 / transport), mirroring ``nwp_client._http_get``. A 4xx such
    as a missing run/lead (404) is permanent and re-raised at once, so a real gap
    surfaces immediately into the run-level failure path instead of being retried.
    """
    last: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = _client().get(url, headers=headers or {})
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
            last = exc
        except httpx.TransportError as exc:
            last = exc
        if attempt < _MAX_RETRIES - 1:
            time.sleep(1.0 * (2 ** attempt))
    assert last is not None  # the loop only leaves early via return or a re-raise
    raise last


def _http_get_bytes(url: str, *, range_header: str | None = None, timeout: float = 60.0) -> bytes:
    headers = {"Range": range_header} if range_header else None
    return _get_with_retry(url, headers).content


def _http_get_text(url: str, *, timeout: float = 60.0) -> str:
    return _get_with_retry(url, None).text


def fetch_tmp_2m_message(run_date: date, run_hour: int, fcst_hour: int) -> tuple[bytes, str]:
    """Fetch ONLY the TMP:2m GRIB message via .idx byte-range. Returns (bytes, range)."""
    idx_text = _http_get_text(gfs_idx_url(run_date, run_hour, fcst_hour))
    msg = find_tmp_2m(parse_idx(idx_text))
    rng = byte_range_header(msg)
    data = _http_get_bytes(gfs_grib_url(run_date, run_hour, fcst_hour), range_header=rng)
    return data, rng


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def decode_tmp_2m_at_point(
    message_bytes: bytes, *, lat: float = NZWN_LAT, lon: float = NZWN_LON
) -> tuple[float, float, float, float]:
    """Decode one TMP:2m GRIB message; nearest-cell value at (lat, lon).

    Returns ``(t2m_c, grid_lat, grid_lon, distance_km)``. eccodes is imported
    LOCALLY so merely importing this module does not pull eccodes onto an import
    graph (defense in depth -- the module is offline-only regardless).
    """
    import eccodes  # local import: offline-only

    # A Range-GET of one .idx entry is a valid standalone GRIB2 message, so decode it
    # straight from memory. (Avoids a temp file whose unlink races eccodes' still-open
    # handle on Windows -> WinError 32.)
    gid = eccodes.codes_new_from_message(message_bytes)
    if gid is None:
        raise ValueError("eccodes could not decode the GRIB message")
    try:
        # GFS longitudes are 0..360; normalize the request.
        req_lon = lon % 360.0
        nearest = eccodes.codes_grib_find_nearest(gid, lat, req_lon)[0]
        t_kelvin = float(nearest.value)
        glat = float(nearest.lat)
        glon = float(nearest.lon)
    finally:
        eccodes.codes_release(gid)

    t_c = t_kelvin - KELVIN_0C
    # report glon back in -180..180 for human comparison with the requested point
    glon_180 = ((glon + 180.0) % 360.0) - 180.0
    dist = _haversine_km(lat, lon, glat, glon_180)
    return t_c, glat, glon_180, dist


def eccodes_version() -> str:
    import eccodes

    return str(eccodes.codes_get_api_version())


__all__ = [
    "NZWN_LAT",
    "NZWN_LON",
    "KELVIN_0C",
    "GfsPoint",
    "DecodeProvenance",
    "fetch_tmp_2m_message",
    "decode_tmp_2m_at_point",
    "eccodes_version",
]
