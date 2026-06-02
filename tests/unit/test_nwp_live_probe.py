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
from core.ingest.nwp_live import ENDPOINT_BY_MODEL, probe_causal_nwp
from core.io.timeutil import cp_to_utc

STATION = "NZWN"
TARGET_DATE = date(2025, 7, 15)
CP = "22:00"  # NZST (UTC+12) -> cp_utc = 2025-07-15T22:00:00Z

# Canonical per-model endpoints (ECMWF single_runs, GFS s3_grib).
ECMWF_EP = ENDPOINT_BY_MODEL[ECMWF_IFS_HRES.id]
GFS_EP = ENDPOINT_BY_MODEL[NCEP_GFS.id]


def _snap_frame(model_id: str, endpoint: str, run_time, valid_time, t2m_c) -> pl.DataFrame:
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


def _write_snap(root, model_id, endpoint, frame: pl.DataFrame):
    """Write to <root>/<station>/<model_id>/<endpoint>/<YYYY>/<MM>.parquet."""
    vt = frame["valid_time_utc"].to_list()[0]
    part = root / STATION / model_id / endpoint / f"{vt.year:04d}"
    part.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(part / f"{vt.month:02d}.parquet")


def test_ecmwf_present_causal_run_available(tmp_path):
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    # ECMWF lives in the single_runs endpoint; causal run 4h before the CP.
    _write_snap(
        tmp_path, ECMWF_IFS_HRES.id, ECMWF_EP,
        _snap_frame(ECMWF_IFS_HRES.id, ECMWF_EP, run_time=cp_utc - timedelta(hours=4),
                    valid_time=cp_utc, t2m_c=14.5),
    )
    probe = probe_causal_nwp(
        station=STATION, target_date=TARGET_DATE, cp_hhmm=CP, out_root=tmp_path
    )
    assert probe.ecmwf_available is True
    assert probe.gfs_available is False
    assert probe.ecmwf_run_time_utc is not None
    assert probe.nwp_run_time_utc == probe.ecmwf_run_time_utc
    assert probe.ecmwf_endpoint == "single_runs"
    assert probe.gfs_endpoint == "s3_grib"


def test_only_gfs_present_in_s3_grib(tmp_path):
    """GFS lives in the s3_grib endpoint (NOT single_runs). With only GFS present and
    ECMWF absent, the probe must still see gfs_available=True (the bug the per-model
    endpoint fix addresses: a single single_runs default made GFS invisible)."""
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    _write_snap(
        tmp_path, NCEP_GFS.id, GFS_EP,
        _snap_frame(NCEP_GFS.id, GFS_EP, run_time=cp_utc - timedelta(hours=4),
                    valid_time=cp_utc, t2m_c=14.0),
    )
    probe = probe_causal_nwp(
        station=STATION, target_date=TARGET_DATE, cp_hhmm=CP, out_root=tmp_path
    )
    assert probe.ecmwf_available is False
    assert probe.gfs_available is True
    # nwp_run_time falls back to the GFS run when ECMWF is absent.
    assert probe.nwp_run_time_utc == probe.gfs_run_time_utc


def test_gfs_in_single_runs_is_not_seen(tmp_path):
    """Guard: a GFS snapshot mistakenly under single_runs is NOT picked up, proving the
    probe reads GFS strictly from s3_grib (the canonical layout)."""
    cp_utc = cp_to_utc(TARGET_DATE, CP)
    _write_snap(
        tmp_path, NCEP_GFS.id, "single_runs",
        _snap_frame(NCEP_GFS.id, "single_runs", run_time=cp_utc - timedelta(hours=4),
                    valid_time=cp_utc, t2m_c=14.0),
    )
    probe = probe_causal_nwp(
        station=STATION, target_date=TARGET_DATE, cp_hhmm=CP, out_root=tmp_path
    )
    assert probe.gfs_available is False


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
        tmp_path, ECMWF_IFS_HRES.id, ECMWF_EP,
        _snap_frame(ECMWF_IFS_HRES.id, ECMWF_EP, run_time=cp_utc - timedelta(minutes=30),
                    valid_time=cp_utc, t2m_c=14.5),
    )
    probe = probe_causal_nwp(
        station=STATION, target_date=TARGET_DATE, cp_hhmm=CP, out_root=tmp_path
    )
    assert probe.ecmwf_available is False
    assert probe.nwp_run_time_utc is None
