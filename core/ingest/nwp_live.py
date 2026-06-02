"""Snapshot-only causal NWP availability probe (Onda 1 / Phase 5 wiring).

Read-only probe over EXISTING local NWP snapshots. No HTTP fetch here: the probe
answers "is there a causal ECMWF/GFS run available for this station/date/CP on
disk?" so that ``forecast --model auto`` can route on real availability instead of
the hardcoded ``_PHASE3_*`` flags.

Causality is delegated to ``select_nwp_v1`` (it filters to runs with
``run_time_utc <= cp_utc - safety_margin``). Missing snapshot roots degrade to
"unavailable" without raising - graceful degradation is the whole point.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from core.ingest.nwp import (
    SAFETY_MARGIN_DEFAULT,
    read_snapshots,
    select_nwp_v1,
)
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS, ModelSpec
from core.io.timeutil import cp_to_utc


DEFAULT_NWP_ROOT = Path("artifacts/raw/nwp")
DEFAULT_ENDPOINT = "single_runs"


@dataclass(frozen=True)
class NwpProbe:
    """Result of a causal NWP availability probe for one station/date/CP."""

    ecmwf_available: bool
    gfs_available: bool
    ecmwf_run_time_utc: str | None
    gfs_run_time_utc: str | None
    nwp_run_time_utc: str | None
    probe_root: str
    endpoint: str


def _probe_one(
    *,
    station: str,
    model: ModelSpec,
    cp_utc,
    target_valid_utc,
    out_root: Path,
    endpoint: str,
    safety_margin: timedelta,
) -> str | None:
    """Return the causal run_time_utc (ISO) if a usable selection exists, else None.

    Any failure to read the snapshot root (missing dir, empty frame) is treated as
    "unavailable": ``read_snapshots`` already returns an empty frame for a missing
    root and ``select_nwp_v1`` returns None for an empty frame, so no raise escapes.
    """
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
    endpoint: str = DEFAULT_ENDPOINT,
    safety_margin: timedelta = SAFETY_MARGIN_DEFAULT,
) -> NwpProbe:
    """Probe local snapshots for a causal ECMWF/GFS run at ``cp_hhmm`` on ``target_date``.

    Uses the Phase-4 causal-at-CP convention: ``target_valid_utc == cp_utc``. The
    returned ``nwp_run_time_utc`` is the ECMWF run if ECMWF is available, else the
    GFS run - the run the router keys off.
    """
    out_root = Path(out_root)
    cp_utc = cp_to_utc(target_date, cp_hhmm)
    target_valid_utc = cp_utc

    ecmwf_run = _probe_one(
        station=station,
        model=ECMWF_IFS_HRES,
        cp_utc=cp_utc,
        target_valid_utc=target_valid_utc,
        out_root=out_root,
        endpoint=endpoint,
        safety_margin=safety_margin,
    )
    gfs_run = _probe_one(
        station=station,
        model=NCEP_GFS,
        cp_utc=cp_utc,
        target_valid_utc=target_valid_utc,
        out_root=out_root,
        endpoint=endpoint,
        safety_margin=safety_margin,
    )

    nwp_run = ecmwf_run if ecmwf_run is not None else gfs_run
    return NwpProbe(
        ecmwf_available=ecmwf_run is not None,
        gfs_available=gfs_run is not None,
        ecmwf_run_time_utc=ecmwf_run,
        gfs_run_time_utc=gfs_run,
        nwp_run_time_utc=nwp_run,
        probe_root=str(out_root),
        endpoint=endpoint,
    )
