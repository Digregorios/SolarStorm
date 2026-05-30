"""NWP ingest unit tests - no real network."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import polars as pl
import pytest

from core.ingest.nwp import (
    NwpSelection,
    SAFETY_MARGIN_DEFAULT,
    select_nwp_ensemble,
    select_nwp_v1,
)
from core.ingest.nwp_client import (
    ECMWF_IFS_HRES,
    NCEP_GFS,
    implied_run_time_hfapi,
)
from core.ingest.nwp_parse import (
    hfapi_response_to_dataframe,
    single_run_response_to_dataframe,
)


def _utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_implied_run_time_hfapi_matches_6h_boundary():
    assert implied_run_time_hfapi(_utc(2025, 7, 1, 2, 0)) == _utc(2025, 7, 1, 0, 0)
    assert implied_run_time_hfapi(_utc(2025, 7, 1, 5, 59)) == _utc(2025, 7, 1, 0, 0)
    assert implied_run_time_hfapi(_utc(2025, 7, 1, 6, 0)) == _utc(2025, 7, 1, 6, 0)
    assert implied_run_time_hfapi(_utc(2025, 7, 1, 23, 30)) == _utc(2025, 7, 1, 18, 0)


def test_implied_run_time_rejects_naive():
    with pytest.raises(ValueError):
        implied_run_time_hfapi(datetime(2025, 7, 1, 2))


def test_hfapi_response_to_dataframe_annotates_run_and_lead():
    payload = {
        "hourly": {
            "time": ["2025-07-01T02:00", "2025-07-01T03:00", "2025-07-01T07:00"],
            "temperature_2m": [10.5, 11.0, 12.5],
            "wind_speed_10m": [5.0, 6.0, 7.0],
            "wind_direction_10m": [180.0, 185.0, 200.0],
            "pressure_msl": [1015.0, 1015.5, 1014.0],
            "cloud_cover": [50, 60, 70],
            "precipitation": [0.0, 0.0, 0.1],
        }
    }
    df = hfapi_response_to_dataframe(payload, station="NZWN", model=ECMWF_IFS_HRES)
    assert df.height == 3
    runs = df["run_time_utc"].to_list()
    assert runs[0] == _utc(2025, 7, 1, 0)
    assert runs[1] == _utc(2025, 7, 1, 0)
    assert runs[2] == _utc(2025, 7, 1, 6)
    assert df["lead_h"].to_list() == [2, 3, 1]
    assert df["model"][0] == "ecmwf_ifs_hres"
    assert df["endpoint"][0] == "hfapi"


def test_single_run_response_uses_explicit_run_time():
    payload = {
        "hourly": {
            "time": ["2025-07-01T01:00", "2025-07-01T03:00"],
            "temperature_2m": [10.0, 11.0],
            "wind_speed_10m": [None, None],
            "wind_direction_10m": [None, None],
            "pressure_msl": [None, None],
            "cloud_cover": [None, None],
            "precipitation": [None, None],
        }
    }
    run = _utc(2025, 7, 1, 0)
    df = single_run_response_to_dataframe(
        payload, station="NZWN", model=ECMWF_IFS_HRES, run_time_utc=run
    )
    assert df["run_time_utc"].to_list() == [run, run]
    assert df["lead_h"].to_list() == [1, 3]
    assert df["endpoint"][0] == "single_runs"


def _build_synthetic_snapshots(rows: list[dict]) -> pl.DataFrame:
    """Helper: build a snapshots frame from a list of dicts."""
    return pl.DataFrame(
        {
            "station": [r.get("station", "NZWN") for r in rows],
            "model": [r["model"] for r in rows],
            "endpoint": [r.get("endpoint", "hfapi") for r in rows],
            "run_time_utc": [r["run_time_utc"] for r in rows],
            "valid_time_utc": [r["valid_time_utc"] for r in rows],
            "lead_h": [int(r.get("lead_h", 0)) for r in rows],
            "t2m_c": [r.get("t2m_c") for r in rows],
            "wind_speed_10m": [r.get("wind_speed_10m") for r in rows],
            "wind_direction_10m": [r.get("wind_direction_10m") for r in rows],
            "pressure_msl": [r.get("pressure_msl") for r in rows],
            "cloud_cover": [r.get("cloud_cover") for r in rows],
            "precipitation": [r.get("precipitation") for r in rows],
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


def test_select_nwp_v1_picks_latest_causal_run():
    """At cp=23 UTC, run_time=18 UTC is causal, run_time=00 UTC of next day is NOT."""
    snapshots = _build_synthetic_snapshots([
        {"model": "ecmwf_ifs_hres", "run_time_utc": _utc(2025, 7, 1, 18),
         "valid_time_utc": _utc(2025, 7, 2, 2), "lead_h": 8, "t2m_c": 14.5},
        {"model": "ecmwf_ifs_hres", "run_time_utc": _utc(2025, 7, 2, 0),
         "valid_time_utc": _utc(2025, 7, 2, 2), "lead_h": 2, "t2m_c": 14.0},
    ])
    cp_utc = _utc(2025, 7, 1, 23)
    target = _utc(2025, 7, 2, 2)
    sel = select_nwp_v1(snapshots, cp_utc=cp_utc, target_valid_utc=target)
    assert sel is not None
    # Cutoff = 23:00 - 60min = 22:00; only the 18 UTC run qualifies
    assert sel.run_time_utc == _utc(2025, 7, 1, 18)
    assert sel.t2m_c == 14.5
    assert sel.lead_h == 8


def test_select_nwp_v1_returns_none_when_no_causal_run():
    snapshots = _build_synthetic_snapshots([
        {"model": "ecmwf_ifs_hres", "run_time_utc": _utc(2025, 7, 2, 0),
         "valid_time_utc": _utc(2025, 7, 2, 2), "lead_h": 2, "t2m_c": 14.0},
    ])
    cp_utc = _utc(2025, 7, 1, 23)
    target = _utc(2025, 7, 2, 2)
    sel = select_nwp_v1(snapshots, cp_utc=cp_utc, target_valid_utc=target)
    assert sel is None


def test_select_nwp_v1_picks_closest_lead_when_target_not_present():
    snapshots = _build_synthetic_snapshots([
        {"model": "ecmwf_ifs_hres", "run_time_utc": _utc(2025, 7, 1, 18),
         "valid_time_utc": _utc(2025, 7, 2, 0), "lead_h": 6, "t2m_c": 13.0},
        {"model": "ecmwf_ifs_hres", "run_time_utc": _utc(2025, 7, 1, 18),
         "valid_time_utc": _utc(2025, 7, 2, 3), "lead_h": 9, "t2m_c": 14.0},
    ])
    cp_utc = _utc(2025, 7, 1, 23)
    target = _utc(2025, 7, 2, 2)
    sel = select_nwp_v1(snapshots, cp_utc=cp_utc, target_valid_utc=target)
    assert sel is not None
    # target=02 UTC closer to valid=03 UTC (|delta|=1h) than to valid=00 UTC (|delta|=2h)
    assert sel.valid_time_utc == _utc(2025, 7, 2, 3)


def test_select_nwp_ensemble_per_model():
    snapshots = _build_synthetic_snapshots([
        {"model": "ecmwf_ifs_hres", "run_time_utc": _utc(2025, 7, 1, 18),
         "valid_time_utc": _utc(2025, 7, 2, 2), "lead_h": 8, "t2m_c": 14.5},
        {"model": "ncep_gfs_global", "run_time_utc": _utc(2025, 7, 1, 18),
         "valid_time_utc": _utc(2025, 7, 2, 2), "lead_h": 8, "t2m_c": 14.0},
    ])
    cp_utc = _utc(2025, 7, 1, 23)
    target = _utc(2025, 7, 2, 2)
    out = select_nwp_ensemble(
        snapshots, cp_utc=cp_utc, target_valid_utc=target,
        models=["ecmwf_ifs_hres", "ncep_gfs_global"],
    )
    assert set(out) == {"ecmwf_ifs_hres", "ncep_gfs_global"}
    assert out["ecmwf_ifs_hres"].t2m_c == 14.5
    assert out["ncep_gfs_global"].t2m_c == 14.0


def test_safety_margin_default_is_60_min():
    assert SAFETY_MARGIN_DEFAULT == timedelta(minutes=60)


def test_select_nwp_v1_naive_datetimes_rejected():
    snapshots = _build_synthetic_snapshots([
        {"model": "ecmwf_ifs_hres", "run_time_utc": _utc(2025, 7, 1, 18),
         "valid_time_utc": _utc(2025, 7, 2, 2), "lead_h": 8, "t2m_c": 14.5},
    ])
    with pytest.raises(ValueError):
        select_nwp_v1(snapshots, cp_utc=datetime(2025, 7, 1, 23),  # naive
                       target_valid_utc=_utc(2025, 7, 2, 2))
