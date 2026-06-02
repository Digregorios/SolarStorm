"""Unit pins for the pure audit helpers (scripts/live_nwp_availability_audit.py).

Synthetic snapshots only -- the full real-data audit is a script entry point and
is NOT run here (mirrors the eval/diagnostic scripts staying out of the suite).
The helpers are verified on constructed inputs with known answers, independent of
the real 5-year panel; causality is delegated to ``select_nwp_v1`` (run_time must
be <= cp_utc - safety), so a run after the cutoff must count as a gap.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from core.ingest.nwp_client import ECMWF_IFS_HRES
from core.io.timeutil import cp_to_utc
from scripts.live_nwp_availability_audit import (
    SAFETY,
    audit_model,
    summarize,
    _any_causal,
    _months_in_window,
    _serving_readiness,
)

STATION = "NZWN"
MODEL_ID = ECMWF_IFS_HRES.id


def _snap_frame(run_time, valid_time, t2m_c) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "station": [STATION],
            "model": [MODEL_ID],
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


def _empty_frame() -> pl.DataFrame:
    return _snap_frame(
        run_time=cp_to_utc(date(2025, 7, 15), "22:00"),
        valid_time=cp_to_utc(date(2025, 7, 15), "22:00"),
        t2m_c=14.0,
    ).clear()


def test_causal_day_covered_gap_day_not(tmp_path):
    """Two days, one CP: the only run is causal for the LATER day but lies in the
    FUTURE relative to the EARLIER day's cutoff -> coverage 0.5, fallback 0.5.

    (A single early run would otherwise be selected for every later day; to make a
    genuine per-day gap, the run must post-date the earlier day's cp-safety cutoff.)
    """
    cp = "22:00"
    d_early, d_late = date(2025, 7, 15), date(2025, 7, 16)
    cp_late = cp_to_utc(d_late, cp)
    # Run 4h before the LATE CP: causal for d_late, but after d_early's cutoff.
    snaps = _snap_frame(run_time=cp_late - timedelta(hours=4), valid_time=cp_late, t2m_c=14.5)

    raw = audit_model(snaps, cp_set=[cp], dates=[d_early, d_late], safety=SAFETY)
    summary = summarize(raw, all_months=_months_in_window([d_early, d_late]))
    s = summary[cp]
    assert s["n_days"] == 2
    assert s["causal"] == 1
    assert s["coverage"] == 0.5
    assert s["fallback_rate"] == 0.5
    assert s["n_gaps"] == 1
    assert s["gaps_first5"] == [d_early.isoformat()]
    # lead_h = 4 (one causal row); run_age = 4h.
    assert s["lead_h"]["median"] == 4.0
    assert s["run_age_h"]["median"] == 4.0


def test_empty_snapshots_zero_coverage_no_raise():
    """Empty frame -> coverage 0.0, fallback 1.0, all days are gaps (graceful)."""
    cp = "22:00"
    d1, d2 = date(2025, 7, 15), date(2025, 7, 16)
    raw = audit_model(_empty_frame(), cp_set=[cp], dates=[d1, d2], safety=SAFETY)
    summary = summarize(raw, all_months=_months_in_window([d1, d2]))
    s = summary[cp]
    assert s["coverage"] == 0.0
    assert s["fallback_rate"] == 1.0
    assert s["n_gaps"] == 2
    # The single (year, month) is missing entirely.
    assert s["n_missing_months"] == 1


def test_run_after_cutoff_counts_as_gap():
    """A run 30min before the CP is AFTER the cp-60min cutoff -> not causal -> gap."""
    cp = "22:00"
    d1 = date(2025, 7, 15)
    cp1 = cp_to_utc(d1, cp)
    snaps = _snap_frame(run_time=cp1 - timedelta(minutes=30), valid_time=cp1, t2m_c=14.5)
    raw = audit_model(snaps, cp_set=[cp], dates=[d1], safety=SAFETY)
    summary = summarize(raw, all_months=_months_in_window([d1]))
    s = summary[cp]
    assert s["causal"] == 0
    assert s["coverage"] == 0.0
    assert s["n_gaps"] == 1


def test_any_causal_unions_models():
    """any_causal: a day is covered if EITHER model is causal.

    model A covers day1 (gap day2); model B covers day2 (gap day1) -> the common
    gap set is empty, so any_causal coverage is 1.0.
    """
    cp = "22:00"
    d1, d2 = date(2025, 7, 15), date(2025, 7, 16)
    per_model_raw = {
        "a": {cp: {"gaps": [d2.isoformat()]}},
        "b": {cp: {"gaps": [d1.isoformat()]}},
    }
    out = _any_causal(per_model_raw, cp_set=[cp], n_days=2)
    assert out[cp]["coverage"] == 1.0
    assert out[cp]["n_gaps"] == 0

    # Both miss day2 -> day2 is a common gap -> coverage 0.5.
    per_model_raw2 = {
        "a": {cp: {"gaps": [d2.isoformat()]}},
        "b": {cp: {"gaps": [d2.isoformat()]}},
    }
    out2 = _any_causal(per_model_raw2, cp_set=[cp], n_days=2)
    assert out2[cp]["coverage"] == 0.5
    assert out2[cp]["gaps_first5"] == [d2.isoformat()]


def test_serving_readiness_only_judges_cp20_22():
    """P3a: serving readiness keys off CP20-22 only; a CP23 gap must NOT mask it,
    and a CP20-22 gap must NOT be diluted by a healthy CP23."""
    # CP20-22 all full, CP23 below threshold -> serving GO (CP23 ignored).
    any_causal = {
        "20:00": {"coverage": 1.0},
        "21:00": {"coverage": 0.995},
        "22:00": {"coverage": 0.99},
        "23:00": {"coverage": 0.50},  # conservative Ridge CP -- irrelevant to serving
    }
    sr = _serving_readiness(any_causal, threshold=0.99)
    assert sr["cps"] == ["20:00", "21:00", "22:00"]
    assert sr["serving_verdict"] == "GO"
    assert sr["serving_offending_cps"] == []

    # A single CP20-22 gap -> serving PAUSE even if CP23 is perfect.
    any_causal2 = {
        "20:00": {"coverage": 0.9556},  # the real-data number today -> PAUSE
        "21:00": {"coverage": 1.0},
        "22:00": {"coverage": 1.0},
        "23:00": {"coverage": 1.0},
    }
    sr2 = _serving_readiness(any_causal2, threshold=0.99)
    assert sr2["serving_verdict"] == "PAUSE"
    assert sr2["serving_offending_cps"] == ["20:00"]
