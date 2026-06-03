from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.ingest.nwp_live import ENDPOINT_BY_MODEL, probe_causal_nwp
from core.io.timeutil import cp_to_utc

STATION = "NZWN"
TARGET_DATE = date(2025, 7, 15)
CP = "22:00"  # cp_utc = 2025-07-15T22:00:00Z
ECMWF_EP = ENDPOINT_BY_MODEL[ECMWF_IFS_HRES.id]
GFS_EP = ENDPOINT_BY_MODEL[NCEP_GFS.id]


def _snap_frame(model_id: str, endpoint: str, run_time: datetime, valid_time: datetime, t2m_c: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "station": [STATION],
            "model": [model_id],
            "endpoint": [endpoint],
            "run_time_utc": [run_time],
            "valid_time_utc": [valid_time],
            "lead_h": [int((valid_time - run_time).total_seconds() // 3600)],
            "t2m_c": [t2m_c],
            "wind_speed_10m": [None],
            "wind_direction_10m": [None],
            "pressure_msl": [None],
            "cloud_cover": [None],
            "precipitation": [None],
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


def _write_snap(root: Path, model_id: str, endpoint: str, frame: pl.DataFrame) -> None:
    vt = frame["valid_time_utc"].to_list()[0]
    part = root / STATION / model_id / endpoint / f"{vt.year:04d}"
    part.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(part / f"{vt.month:02d}.parquet")


def _merge_snap(root: Path, model_id: str, endpoint: str, frame: pl.DataFrame) -> None:
    """Merge *frame* into the existing parquet partition (concat, not overwrite).

    This mirrors production _write_partitioned semantics: new rows are appended
    to existing data and de-duplicated by (model, endpoint, run_time_utc,
    valid_time_utc), keeping the latest entry.
    """
    vt = frame["valid_time_utc"].to_list()[0]
    part = root / STATION / model_id / endpoint / f"{vt.year:04d}"
    part.mkdir(parents=True, exist_ok=True)
    path = part / f"{vt.month:02d}.parquet"
    if path.exists():
        existing = pl.read_parquet(path)
        merged = pl.concat([existing, frame], how="vertical_relaxed")
        merged = merged.unique(
            subset=["model", "endpoint", "run_time_utc", "valid_time_utc"],
            keep="last",
        )
        merged.write_parquet(path)
    else:
        frame.write_parquet(path)


def test_live_fetch_no_op_when_cached(tmp_path):
    """If the target run is already cached, fetch_live must not trigger any fetches."""
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    # Expected run time for CP 22:00 UTC (cutoff 21:00 UTC) is 18:00 UTC
    expected_run = cp_utc.replace(hour=18, minute=0, second=0, microsecond=0)

    _write_snap(
        tmp_path, ECMWF_IFS_HRES.id, ECMWF_EP,
        _snap_frame(ECMWF_IFS_HRES.id, ECMWF_EP, run_time=expected_run,
                    valid_time=cp_utc, t2m_c=14.5),
    )
    _write_snap(
        tmp_path, NCEP_GFS.id, GFS_EP,
        _snap_frame(NCEP_GFS.id, GFS_EP, run_time=expected_run,
                    valid_time=cp_utc, t2m_c=14.0),
    )

    with patch("core.ingest.nwp.snapshot_single_run") as mock_snapshot:
        probe = probe_causal_nwp(
            station=STATION,
            target_date=TARGET_DATE,
            cp_hhmm=CP,
            out_root=tmp_path,
            fetch_live=True,
            lat=-41.3272,
            lon=174.8053,
        )
        assert mock_snapshot.call_count == 0
        assert probe.ecmwf_available is True
        assert probe.ecmwf_run_time_utc == expected_run.isoformat()


def test_live_fetch_triggers_fetch_when_missing(tmp_path):
    """If expected run is not cached, fetch_live must try to fetch it and update local cache."""
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    expected_run = cp_utc.replace(hour=18, minute=0, second=0, microsecond=0)

    # Mock fetch function to write a mock file to the local directory
    def side_effect(lat, lon, station, model, run_time_utc, out_root, endpoint):
        frame = _snap_frame(model.id, endpoint, run_time=run_time_utc, valid_time=cp_utc, t2m_c=15.0)
        _write_snap(Path(out_root), model.id, endpoint, frame)

    with patch("core.ingest.nwp.snapshot_single_run", side_effect=side_effect) as mock_snapshot:
        probe = probe_causal_nwp(
            station=STATION,
            target_date=TARGET_DATE,
            cp_hhmm=CP,
            out_root=tmp_path,
            fetch_live=True,
            lat=-41.3272,
            lon=174.8053,
        )
        # ECMWF should be fetched first and then GFS
        assert mock_snapshot.call_count == 2
        
        # Verify ECMWF call args
        mock_snapshot.assert_any_call(
            lat=-41.3272,
            lon=174.8053,
            station=STATION,
            model=ECMWF_IFS_HRES,
            run_time_utc=expected_run,
            out_root=tmp_path,
            endpoint=ECMWF_EP,
        )
        # Verify GFS call args
        mock_snapshot.assert_any_call(
            lat=-41.3272,
            lon=174.8053,
            station=STATION,
            model=NCEP_GFS,
            run_time_utc=expected_run,
            out_root=tmp_path,
            endpoint=GFS_EP,
        )

        assert probe.ecmwf_available is True
        assert probe.gfs_available is True
        assert probe.ecmwf_run_time_utc == expected_run.isoformat()


def test_live_fetch_falls_back_to_older_cycles_on_delay(tmp_path):
    """If the latest cycle returns 400 (not published), it must check and fall back to the previous cycle."""
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    expected_run = cp_utc.replace(hour=18, minute=0, second=0, microsecond=0)
    fallback_run = expected_run - timedelta(hours=6)  # 12Z run

    # 18Z run will fail to fetch (not published), 12Z run will succeed
    def side_effect(lat, lon, station, model, run_time_utc, out_root, endpoint):
        if run_time_utc == expected_run:
            raise RuntimeError("Open-Meteo GET failed: HTTP Error 400 Bad Request")
        frame = _snap_frame(model.id, endpoint, run_time=run_time_utc, valid_time=cp_utc, t2m_c=13.0)
        _write_snap(Path(out_root), model.id, endpoint, frame)

    with patch("core.ingest.nwp.snapshot_single_run", side_effect=side_effect) as mock_snapshot:
        probe = probe_causal_nwp(
            station=STATION,
            target_date=TARGET_DATE,
            cp_hhmm=CP,
            out_root=tmp_path,
            fetch_live=True,
            lat=-41.3272,
            lon=174.8053,
        )
        # Should call 18Z (fail), then 12Z (success) for both ECMWF and GFS
        assert mock_snapshot.call_count == 4
        assert probe.ecmwf_available is True
        assert probe.ecmwf_run_time_utc == fallback_run.isoformat()


def test_live_fetch_degrades_gracefully_when_all_fail(tmp_path):
    """If all candidate cycles fail to fetch, the probe must degrade gracefully to unavailable without raising."""
    with patch("core.ingest.nwp.snapshot_single_run", side_effect=RuntimeError("HTTP Error 404 Not Found")):
        probe = probe_causal_nwp(
            station=STATION,
            target_date=TARGET_DATE,
            cp_hhmm=CP,
            out_root=tmp_path,
            fetch_live=True,
            lat=-41.3272,
            lon=174.8053,
        )
        assert probe.ecmwf_available is False
        assert probe.gfs_available is False


def test_live_fetch_repairs_incomplete_cache(tmp_path):
    """If a run is cached but lacks valid forecast points (t2m_c is None), we treat it as miss and re-download/repair."""
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    expected_run = cp_utc.replace(hour=18, minute=0, second=0, microsecond=0)

    # Cache an incomplete frame (t2m_c is None)
    _write_snap(
        tmp_path, ECMWF_IFS_HRES.id, ECMWF_EP,
        _snap_frame(ECMWF_IFS_HRES.id, ECMWF_EP, run_time=expected_run,
                    valid_time=cp_utc, t2m_c=None),
    )

    def side_effect(lat, lon, station, model, run_time_utc, out_root, endpoint):
        frame = _snap_frame(model.id, endpoint, run_time=run_time_utc, valid_time=cp_utc, t2m_c=16.0)
        _write_snap(Path(out_root), model.id, endpoint, frame)

    with patch("core.ingest.nwp.snapshot_single_run", side_effect=side_effect) as mock_snapshot:
        probe = probe_causal_nwp(
            station=STATION,
            target_date=TARGET_DATE,
            cp_hhmm=CP,
            out_root=tmp_path,
            fetch_live=True,
            lat=-41.3272,
            lon=174.8053,
        )
        # ECMWF should be re-downloaded to repair the cache
        assert mock_snapshot.call_count > 0
        assert probe.ecmwf_available is True
        assert probe.ecmwf_run_time_utc == expected_run.isoformat()


def test_live_fetch_records_full_telemetry(tmp_path):
    """Verify that NwpProbe correctly captures all expanded telemetry fields for fetch and cache statuses."""
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    expected_run = cp_utc.replace(hour=18, minute=0, second=0, microsecond=0)

    # 1) Fetch Disabled
    probe_disabled = probe_causal_nwp(
        station=STATION,
        target_date=TARGET_DATE,
        cp_hhmm=CP,
        out_root=tmp_path,
        fetch_live=False,
    )
    assert probe_disabled.ecmwf_fetch_attempted is False
    assert probe_disabled.ecmwf_fetch_status == "fetch_disabled"
    assert probe_disabled.ecmwf_cache_hit is False

    # 2) Cache Hit
    _write_snap(
        tmp_path, ECMWF_IFS_HRES.id, ECMWF_EP,
        _snap_frame(ECMWF_IFS_HRES.id, ECMWF_EP, run_time=expected_run,
                    valid_time=cp_utc, t2m_c=14.5),
    )
    with patch("core.ingest.nwp.snapshot_single_run") as mock_snap:
        probe_hit = probe_causal_nwp(
            station=STATION,
            target_date=TARGET_DATE,
            cp_hhmm=CP,
            out_root=tmp_path,
            fetch_live=True,
            lat=-41.3272,
            lon=174.8053,
        )
    assert probe_hit.ecmwf_fetch_attempted is True
    assert probe_hit.ecmwf_cache_hit is True
    assert probe_hit.ecmwf_fetch_status == "cache_hit"
    assert len(probe_hit.ecmwf_candidate_run_times) == 4
    assert len(probe_hit.ecmwf_http_attempted_run_times) == 0
    assert probe_hit.ecmwf_selected_run_time == expected_run.isoformat()
    assert probe_hit.ecmwf_fetch_error_type is None

    # 3) Fetch Success (reusing tmp_path but for GFS which is missing)
    def side_effect(lat, lon, station, model, run_time_utc, out_root, endpoint):
        frame = _snap_frame(model.id, endpoint, run_time=run_time_utc, valid_time=cp_utc, t2m_c=12.5)
        _write_snap(Path(out_root), model.id, endpoint, frame)

    with patch("core.ingest.nwp.snapshot_single_run", side_effect=side_effect):
        probe_success = probe_causal_nwp(
            station=STATION,
            target_date=TARGET_DATE,
            cp_hhmm=CP,
            out_root=tmp_path,
            fetch_live=True,
            lat=-41.3272,
            lon=174.8053,
        )
        assert probe_success.gfs_fetch_attempted is True
        assert probe_success.gfs_cache_hit is False
        assert probe_success.gfs_fetch_status == "success"
        assert probe_success.gfs_fetch_error_type is None

    # 4) Fetch Failed
    with patch("core.ingest.nwp.snapshot_single_run", side_effect=RuntimeError("Connection Timeout")):
        # Clear cache first by mock out_root using a new subdir
        fail_path = tmp_path / "fail_sub"
        probe_fail = probe_causal_nwp(
            station=STATION,
            target_date=TARGET_DATE,
            cp_hhmm=CP,
            out_root=fail_path,
            fetch_live=True,
            lat=-41.3272,
            lon=174.8053,
        )
        assert probe_fail.ecmwf_fetch_attempted is True
        assert probe_fail.ecmwf_cache_hit is False
        assert probe_fail.ecmwf_fetch_status == "failed"
        assert probe_fail.ecmwf_fetch_error_type == "RuntimeError"
        assert len(probe_fail.ecmwf_http_attempted_run_times) == 4
        assert probe_fail.ecmwf_selected_run_time is None


def test_live_fetch_validates_downloaded_snapshot_before_break(tmp_path):
    """If latest cycle downloads but t2m_c is unusable for CP, loop must continue
    to older cycles. Uses _merge_snap (concat) to replicate real production cache
    write semantics where an invalid newer run coexists with an older valid run
    in the same parquet partition.
    """
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    expected_run = cp_utc.replace(hour=18, minute=0, second=0, microsecond=0)
    fallback_run = expected_run - timedelta(hours=6)  # 12Z run

    def side_effect(lat, lon, station, model, run_time_utc, out_root, endpoint):
        if run_time_utc == expected_run:
            # Latest cycle downloads but produces unusable data for this CP (t2m_c=None).
            # _merge_snap preserves any previously written runs in the same partition.
            frame = _snap_frame(model.id, endpoint, run_time=run_time_utc,
                                valid_time=cp_utc, t2m_c=None)
            _merge_snap(Path(out_root), model.id, endpoint, frame)
        else:
            # Older cycle has usable data.
            frame = _snap_frame(model.id, endpoint, run_time=run_time_utc,
                                valid_time=cp_utc, t2m_c=13.5)
            _merge_snap(Path(out_root), model.id, endpoint, frame)

    with patch("core.ingest.nwp.snapshot_single_run", side_effect=side_effect) as mock_snapshot:
        probe = probe_causal_nwp(
            station=STATION,
            target_date=TARGET_DATE,
            cp_hhmm=CP,
            out_root=tmp_path,
            fetch_live=True,
            lat=-41.3272,
            lon=174.8053,
        )
        # Latest cycle was fetched but unusable, so fallback to older cycle.
        # ECMWF: 18Z (downloaded but invalid) -> 12Z (downloaded and valid)
        # GFS: same pattern
        assert mock_snapshot.call_count >= 2
        assert probe.ecmwf_available is True
        assert probe.ecmwf_run_time_utc == fallback_run.isoformat()
        assert probe.ecmwf_fetch_status == "success"
        assert probe.ecmwf_selected_run_time == fallback_run.isoformat()
