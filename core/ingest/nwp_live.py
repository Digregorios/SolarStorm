"""Snapshot-only causal NWP availability probe (Onda 1 / Phase 5 wiring).

Read-only probe over EXISTING local NWP snapshots. No HTTP fetch here: the probe
answers "is there a causal ECMWF/GFS run available for this station/date/CP on
disk?" so that ``forecast --model auto`` can route on real availability instead of
the hardcoded ``_PHASE3_*`` flags.

Endpoints are per-model: the canonical project layout stores ECMWF under
``single_runs`` and GFS under ``s3_grib`` (see the eval / serving-matrix scripts).
A single shared default would make GFS invisible and force CP20-22 to ridge even
when a causal GFS run exists -- so the probe keys the endpoint off the model.

Causality is delegated to ``select_nwp_v1`` (it filters to runs with
``run_time_utc <= cp_utc - safety_margin``). Missing snapshot roots degrade to
"unavailable" without raising - graceful degradation is the whole point.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from core.ingest.nwp import (
    SAFETY_MARGIN_DEFAULT,
    read_snapshots,
    select_nwp_v1,
)
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS, ModelSpec
from core.io.timeutil import cp_to_utc


DEFAULT_NWP_ROOT = Path("artifacts/raw/nwp")

# Canonical per-model snapshot endpoints (must match the eval / serving-matrix
# scripts: ECMWF -> single_runs, GFS -> s3_grib). Keyed by ModelSpec.id.
ENDPOINT_BY_MODEL: dict[str, str] = {
    ECMWF_IFS_HRES.id: "single_runs",
    NCEP_GFS.id: "s3_grib",
}


@dataclass(frozen=True)
class NwpProbe:
    """Result of a causal NWP availability probe for one station/date/CP."""

    ecmwf_available: bool
    gfs_available: bool
    ecmwf_run_time_utc: str | None
    gfs_run_time_utc: str | None
    nwp_run_time_utc: str | None
    probe_root: str
    ecmwf_endpoint: str
    gfs_endpoint: str


def _probe_one(
    *,
    station: str,
    model: ModelSpec,
    cp_utc: datetime,
    target_valid_utc: datetime,
    out_root: Path,
    endpoint: str,
    safety_margin: timedelta,
    fetch_live: bool = False,
    lat: float | None = None,
    lon: float | None = None,
) -> str | None:
    """Return the causal run_time_utc (ISO) if a usable selection exists, else None.

    Any failure to read the snapshot root (missing dir, empty frame) is treated as
    "unavailable": ``read_snapshots`` already returns an empty frame for a missing
    root and ``select_nwp_v1`` returns None for an empty frame, so no raise escapes.
    """
    if fetch_live and lat is not None and lon is not None:
        # Determine candidate run times starting from the latest cycle <= cutoff.
        # Cycle hours are 6-hourly: 00, 06, 12, 18 UTC.
        cutoff = cp_utc - safety_margin
        base = cutoff.replace(minute=0, second=0, microsecond=0)
        h = (base.hour // 6) * 6
        expected_latest = base.replace(hour=h)
        candidates = [expected_latest - timedelta(hours=6 * i) for i in range(4)]

        try:
            snaps = read_snapshots(
                station=station, model=model, endpoint=endpoint, out_root=out_root
            )
            if snaps.height > 0:
                col = snaps["run_time_utc"]
                if col.dtype.time_zone is not None:
                    col = col.dt.replace_time_zone(None)
                cached_runs = set(col.to_list())
            else:
                cached_runs = set()
        except Exception:
            cached_runs = set()

        for cand in candidates:
            cand_naive = cand.replace(tzinfo=None)
            if cand_naive in cached_runs:
                # Latest causal run available is already cached. Stop checking older ones.
                break
            else:
                # Not cached. Attempt to download it.
                try:
                    from core.ingest.nwp import snapshot_single_run
                    import typer
                    typer.echo(
                        f"[live-nwp] Fetching {model.id} run_time={cand.isoformat()} for CP {cp_utc.isoformat()}...",
                        err=True,
                    )
                    snapshot_single_run(
                        lat=lat,
                        lon=lon,
                        station=station,
                        model=model,
                        run_time_utc=cand,
                        out_root=out_root,
                        endpoint=endpoint,
                    )
                    # Successfully fetched and saved to cache!
                    break
                except Exception as exc:
                    import typer
                    exc_msg = str(exc)
                    if "400" in exc_msg or "404" in exc_msg:
                        typer.echo(
                            f"[live-nwp] {model.id} run_time={cand.isoformat()} not published yet. Checking older runs...",
                            err=True,
                        )
                    else:
                        typer.echo(
                            f"[live-nwp] Failed to fetch {model.id} run_time={cand.isoformat()}: {exc_msg}. Checking older...",
                            err=True,
                        )

    try:
        snaps = read_snapshots(
            station=station, model=model, endpoint=endpoint, out_root=out_root
        )
    except (OSError, ValueError):
        return None
    sel = select_nwp_v1(
        snaps,
        cp_utc=cp_utc,
        target_valid_utc=target_valid_utc,
        safety_margin=safety_margin,
    )
    if sel is None or sel.t2m_c is None:
        return None
    return sel.run_time_utc.isoformat()


def probe_causal_nwp(
    *,
    station: str,
    target_date: date,
    cp_hhmm: str,
    out_root: Path | str = DEFAULT_NWP_ROOT,
    ecmwf_endpoint: str | None = None,
    gfs_endpoint: str | None = None,
    safety_margin: timedelta = SAFETY_MARGIN_DEFAULT,
    fetch_live: bool = False,
    lat: float | None = None,
    lon: float | None = None,
) -> NwpProbe:
    """Probe local snapshots for a causal ECMWF/GFS run at ``cp_hhmm`` on ``target_date``.

    Endpoints default per-model (ECMWF ``single_runs``, GFS ``s3_grib``); override
    only for tests or non-canonical layouts. Uses the Phase-4 causal-at-CP convention
    (``target_valid_utc == cp_utc``). ``nwp_run_time_utc`` is the ECMWF run if ECMWF
    is available, else the GFS run - the run the router keys off.
    """
    out_root = Path(out_root)
    ecmwf_ep = ecmwf_endpoint or ENDPOINT_BY_MODEL[ECMWF_IFS_HRES.id]
    gfs_ep = gfs_endpoint or ENDPOINT_BY_MODEL[NCEP_GFS.id]
    cp_utc = cp_to_utc(target_date, cp_hhmm)
    target_valid_utc = cp_utc

    ecmwf_run = _probe_one(
        station=station,
        model=ECMWF_IFS_HRES,
        cp_utc=cp_utc,
        target_valid_utc=target_valid_utc,
        out_root=out_root,
        endpoint=ecmwf_ep,
        safety_margin=safety_margin,
        fetch_live=fetch_live,
        lat=lat,
        lon=lon,
    )
    gfs_run = _probe_one(
        station=station,
        model=NCEP_GFS,
        cp_utc=cp_utc,
        target_valid_utc=target_valid_utc,
        out_root=out_root,
        endpoint=gfs_ep,
        safety_margin=safety_margin,
        fetch_live=fetch_live,
        lat=lat,
        lon=lon,
    )

    nwp_run = ecmwf_run if ecmwf_run is not None else gfs_run
    return NwpProbe(
        ecmwf_available=ecmwf_run is not None,
        gfs_available=gfs_run is not None,
        ecmwf_run_time_utc=ecmwf_run,
        gfs_run_time_utc=gfs_run,
        nwp_run_time_utc=nwp_run,
        probe_root=str(out_root),
        ecmwf_endpoint=ecmwf_ep,
        gfs_endpoint=gfs_ep,
    )
