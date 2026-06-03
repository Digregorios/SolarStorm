"""Causal NWP availability probe (Onda 1 / Phase 5 wiring).

Probes local NWP snapshots to answer "is there a causal ECMWF/GFS run available for this
station/date/CP on disk?" so that ``forecast --model auto`` can route on real availability.
Supports optional live download fetching/caching (`fetch_live=True`) to fetch and self-repair
incomplete cached snapshots over a lookback window of 4 expected cycles (up to 18h lookback).

Endpoints are per-model: the canonical project layout stores ECMWF under
``single_runs`` and GFS under ``s3_grib`` (see the eval / serving-matrix scripts).
A single shared default would make GFS invisible and force CP20-22 to ridge even
when a causal GFS run exists -- so the probe keys the endpoint off the model.

Causality is delegated to ``select_nwp_v1`` (it filters to runs with
``run_time_utc <= cp_utc - safety_margin``). Missing snapshot roots degrade to
"unavailable" without raising - graceful degradation is the whole point.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from core.ingest.nwp import (
    SAFETY_MARGIN_DEFAULT,
    read_snapshots,
    select_nwp_v1,
)
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS, ModelSpec
from core.io.timeutil import cp_to_utc

_log = logging.getLogger(__name__)


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

    ecmwf_fetch_attempted: bool = False
    ecmwf_cache_hit: bool = False
    ecmwf_fetch_status: str = "fetch_disabled"
    ecmwf_candidate_run_times: list[str] = field(default_factory=list)
    ecmwf_http_attempted_run_times: list[str] = field(default_factory=list)
    ecmwf_selected_run_time: str | None = None
    ecmwf_fetch_error_type: str | None = None

    gfs_fetch_attempted: bool = False
    gfs_cache_hit: bool = False
    gfs_fetch_status: str = "fetch_disabled"
    gfs_candidate_run_times: list[str] = field(default_factory=list)
    gfs_http_attempted_run_times: list[str] = field(default_factory=list)
    gfs_selected_run_time: str | None = None
    gfs_fetch_error_type: str | None = None


@dataclass(frozen=True)
class _ModelProbeResult:
    run_time_utc: str | None
    fetch_attempted: bool
    cache_hit: bool
    fetch_status: str
    candidate_run_times: list[str]
    http_attempted_run_times: list[str]
    selected_run_time: str | None
    fetch_error_type: str | None


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
) -> _ModelProbeResult:
    """Return the _ModelProbeResult containing causal run_time_utc and telemetry."""
    fetch_attempted = False
    cache_hit = False
    fetch_status = "fetch_disabled"
    candidate_run_times: list[str] = []
    http_attempted_run_times: list[str] = []
    selected_run_time: str | None = None
    fetch_error_type: str | None = None
    cache_validation_error_type: str | None = None

    if fetch_live:
        if lat is None or lon is None:
            fetch_status = "lat_lon_missing"
        else:
            fetch_attempted = True
            cutoff = cp_utc - safety_margin
            base = cutoff.replace(minute=0, second=0, microsecond=0)
            h = (base.hour // 6) * 6
            expected_latest = base.replace(hour=h)
            candidates = [expected_latest - timedelta(hours=6 * i) for i in range(4)]
            candidate_run_times = [c.isoformat() for c in candidates]

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

            cache_valid_found = False
            for cand in candidates:
                cand_naive = cand.replace(tzinfo=None)
                cache_valid = False
                if cand_naive in cached_runs:
                    try:
                        if snaps["run_time_utc"].dtype.time_zone is not None:
                            cand_snap = snaps.filter(pl.col("run_time_utc") == cand)
                        else:
                            cand_snap = snaps.filter(pl.col("run_time_utc") == cand_naive)
                        sel = select_nwp_v1(
                            cand_snap,
                            cp_utc=cp_utc,
                            target_valid_utc=target_valid_utc,
                            safety_margin=safety_margin,
                        )
                        if sel is not None and sel.t2m_c is not None:
                            cache_valid = True
                    except Exception as e:
                        cache_validation_error_type = type(e).__name__
                        _log.debug(
                            "cache_validation_error model=%s run_time=%s error_type=%s",
                            model.id, cand.isoformat(), cache_validation_error_type,
                        )

                if cache_valid:
                    cache_hit = True
                    fetch_status = "cache_hit"
                    selected_run_time = cand.isoformat()
                    cache_valid_found = True
                    break
                else:
                    try:
                        from core.ingest.nwp import snapshot_single_run
                        import typer
                        http_attempted_run_times.append(cand.isoformat())
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
                        # Validate freshly downloaded snapshot before stopping.
                        # Filter to this candidate's run_time so a newer unusable run
                        # already in cache cannot shadow it via select_nwp_v1 (which
                        # picks the latest causal run).
                        try:
                            dl_snaps = read_snapshots(
                                station=station, model=model,
                                endpoint=endpoint, out_root=out_root,
                            )
                            if dl_snaps["run_time_utc"].dtype.time_zone is not None:
                                cand_dl = dl_snaps.filter(
                                    pl.col("run_time_utc") == cand
                                )
                            else:
                                cand_dl = dl_snaps.filter(
                                    pl.col("run_time_utc") == cand_naive
                                )
                            dl_sel = select_nwp_v1(
                                cand_dl,
                                cp_utc=cp_utc,
                                target_valid_utc=target_valid_utc,
                                safety_margin=safety_margin,
                            )
                            if dl_sel is not None and dl_sel.t2m_c is not None:
                                fetch_status = "success"
                                selected_run_time = cand.isoformat()
                                cache_valid_found = True
                                break
                            else:
                                # Downloaded but unusable for this CP -- try older cycle.
                                import typer as _t
                                _t.echo(
                                    f"[live-nwp] {model.id} run_time={cand.isoformat()} downloaded but t2m_c unusable for CP. Trying older...",
                                    err=True,
                                )
                                fetch_error_type = "t2m_c_unusable"
                        except Exception as dl_exc:
                            fetch_error_type = type(dl_exc).__name__
                            _log.debug(
                                "post_download_validation_error model=%s run_time=%s error_type=%s",
                                model.id, cand.isoformat(), fetch_error_type,
                            )
                    except Exception as exc:
                        exc_type = type(exc).__name__
                        fetch_error_type = exc_type
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

            if not cache_valid_found:
                fetch_status = "failed"

    # Final selection: if the loop validated a specific candidate, scope the final
    # select_nwp_v1 to that run_time so a newer unusable run on disk cannot shadow
    # it (select_nwp_v1 always picks the latest causal run).
    try:
        snaps = read_snapshots(
            station=station, model=model, endpoint=endpoint, out_root=out_root
        )
    except (OSError, ValueError):
        return _ModelProbeResult(
            run_time_utc=None,
            fetch_attempted=fetch_attempted,
            cache_hit=cache_hit,
            fetch_status=fetch_status if fetch_status != "fetch_disabled" else "failed",
            candidate_run_times=candidate_run_times,
            http_attempted_run_times=http_attempted_run_times,
            selected_run_time=selected_run_time,
            fetch_error_type=fetch_error_type or "OSError",
        )

    if selected_run_time is not None:
        # Scope to the validated candidate so newer broken runs can't shadow it.
        sel_rt = datetime.fromisoformat(selected_run_time)
        if snaps["run_time_utc"].dtype.time_zone is not None:
            final_snaps = snaps.filter(pl.col("run_time_utc") == sel_rt)
        else:
            final_snaps = snaps.filter(
                pl.col("run_time_utc") == sel_rt.replace(tzinfo=None)
            )
    else:
        final_snaps = snaps

    sel = select_nwp_v1(
        final_snaps,
        cp_utc=cp_utc,
        target_valid_utc=target_valid_utc,
        safety_margin=safety_margin,
    )
    if sel is None or sel.t2m_c is None:
        return _ModelProbeResult(
            run_time_utc=None,
            fetch_attempted=fetch_attempted,
            cache_hit=cache_hit,
            fetch_status=fetch_status if fetch_status not in ("cache_hit", "success") else "failed",
            candidate_run_times=candidate_run_times,
            http_attempted_run_times=http_attempted_run_times,
            selected_run_time=None,
            fetch_error_type=fetch_error_type,
        )

    final_run_time = sel.run_time_utc.isoformat()
    return _ModelProbeResult(
        run_time_utc=final_run_time,
        fetch_attempted=fetch_attempted,
        cache_hit=cache_hit,
        fetch_status=fetch_status,
        candidate_run_times=candidate_run_times,
        http_attempted_run_times=http_attempted_run_times,
        selected_run_time=selected_run_time or final_run_time,
        fetch_error_type=None if fetch_status in ("cache_hit", "success") else fetch_error_type,
    )


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

    ecmwf_res = _probe_one(
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
    gfs_res = _probe_one(
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

    ecmwf_run = ecmwf_res.run_time_utc
    gfs_run = gfs_res.run_time_utc
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
        ecmwf_fetch_attempted=ecmwf_res.fetch_attempted,
        ecmwf_cache_hit=ecmwf_res.cache_hit,
        ecmwf_fetch_status=ecmwf_res.fetch_status,
        ecmwf_candidate_run_times=ecmwf_res.candidate_run_times,
        ecmwf_http_attempted_run_times=ecmwf_res.http_attempted_run_times,
        ecmwf_selected_run_time=ecmwf_res.selected_run_time,
        ecmwf_fetch_error_type=ecmwf_res.fetch_error_type,
        gfs_fetch_attempted=gfs_res.fetch_attempted,
        gfs_cache_hit=gfs_res.cache_hit,
        gfs_fetch_status=gfs_res.fetch_status,
        gfs_candidate_run_times=gfs_res.candidate_run_times,
        gfs_http_attempted_run_times=gfs_res.http_attempted_run_times,
        gfs_selected_run_time=gfs_res.selected_run_time,
        gfs_fetch_error_type=gfs_res.fetch_error_type,
    )
