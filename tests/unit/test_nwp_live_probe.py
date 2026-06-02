"""Unit tests for the snapshot-only causal NWP probe (core/ingest/nwp_live.py).

No network: synthetic snapshots are written to a tmp_path partition layout that
``read_snapshots`` reads. Causality is enforced by ``select_nwp_v1`` (run_time must
be <= cp_utc - safety_margin); missing roots must degrade to "unavailable" without
raising.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.ingest.nwp_live import probe_causal_nwp
from core.io.timeutil import cp_to_utc

STATION = "NZWN"
TARGET_DATE = date(2025, 7, 15)
CP = "22:00"  # NZST (UTC+12) -> cp_utc = 2025-07-15T22:00:00Z


def _snap_frame(model_id: str, run_time, valid_time, t2m_c) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "station": [STATION],
            "model": [model_id],
            "endpoint": ["single_runs"],
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


def _write_snap(root, model_id, frame: pl.DataFrame):
    """Write to the canonical <root>/<station>/<model_id>/single_runs/<YYYY>/<MM>.parquet."""
    vt = frame["valid_time_utc"].to_list()[0]
    part = root / STATION / model_id / "single_runs" / f"{vt.year:04d}"
    part.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(part / f"{vt.month:02d}.parquet")


def test_ecmwf_present_causal_run_available(tmp_path):
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    # Causal run: 4h before the CP (well past the 60min safety margin cutoff).
    _write_snap(
        tmp_path, ECMWF_IFS_HRES.id,
        _snap_frame(ECMWF_IFS_HRES.id, run_time=cp_utc - timedelta(hours=4),
                    valid_time=cp_utc, t2m_c=14.5),
    )
    probe = probe_causal_nwp(
        station=STATION, target_date=TARGET_DATE, cp_hhmm=CP, out_root=tmp_path
    )
    assert probe.ecmwf_available is True
    assert probe.gfs_available is False
    assert probe.ecmwf_run_time_utc is not None
    assert probe.nwp_run_time_utc == probe.ecmwf_run_time_utc


def test_only_gfs_present(tmp_path):
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    _write_snap(
        tmp_path, NCEP_GFS.id,
        _snap_frame(NCEP_GFS.id, run_time=cp_utc - timedelta(hours=4),
                    valid_time=cp_utc, t2m_c=14.0),
    )
    probe = probe_causal_nwp(
        station=STATION, target_date=TARGET_DATE, cp_hhmm=CP, out_root=tmp_path
    )
    assert probe.ecmwf_available is False
    assert probe.gfs_available is True
    # nwp_run_time falls back to the GFS run when ECMWF is absent.
    assert probe.nwp_run_time_utc == probe.gfs_run_time_utc


def test_missing_root_degrades_without_raising(tmp_path):
    probe = probe_causal_nwp(
        station=STATION, target_date=TARGET_DATE, cp_hhmm=CP,
        out_root=tmp_path / "does_not_exist",
    )
    assert probe.ecmwf_available is False
    assert probe.gfs_available is False
    assert probe.ecmwf_run_time_utc is None
    assert probe.gfs_run_time_utc is None
    assert probe.nwp_run_time_utc is None


def test_run_after_cutoff_is_not_causal(tmp_path):
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    # Run 30min before the CP is AFTER the cutoff (cp - 60min) -> not causal.
    _write_snap(
        tmp_path, ECMWF_IFS_HRES.id,
        _snap_frame(ECMWF_IFS_HRES.id, run_time=cp_utc - timedelta(minutes=30),
                    valid_time=cp_utc, t2m_c=14.5),
    )
    probe = probe_causal_nwp(
        station=STATION, target_date=TARGET_DATE, cp_hhmm=CP, out_root=tmp_path
    )
    assert probe.ecmwf_available is False
    assert probe.nwp_run_time_utc is None
