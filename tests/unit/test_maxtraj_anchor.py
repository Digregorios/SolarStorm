"""Max-of-trajectory causal anchor + Tmax-hour climatology (design 4.5.2.1, C1).

These exercise the NWP_SOURCE_VERSION 1.1 anchor:
- ``select_max_trajectory_anchor`` must take the MAX over a forward valid-time
  window from a SINGLE causal run, ensemble-mean across models, and never pull a
  non-causal (too-fresh) run - that is the whole point of the re-anchoring.
- ``fit_tmax_hour_climatology`` must produce a sane per-month local-hour window
  and refuse regime conditioning while the GMM artifact does not exist.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from core.baselines.climatology import (
    TmaxHourClimatology,
    fit_tmax_hour_climatology,
)
from core.features.nwp import MaxTrajAnchor, select_max_trajectory_anchor


def _utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def _snapshots(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "model": [r["model"] for r in rows],
            "run_time_utc": [r["run_time_utc"] for r in rows],
            "valid_time_utc": [r["valid_time_utc"] for r in rows],
            "lead_h": [
                int(r.get("lead_h", (r["valid_time_utc"] - r["run_time_utc"]).total_seconds() / 3600))
                for r in rows
            ],
            "t2m_c": [r.get("t2m_c") for r in rows],
        },
        schema={
            "model": pl.Utf8,
            "run_time_utc": pl.Datetime("us", time_zone="UTC"),
            "valid_time_utc": pl.Datetime("us", time_zone="UTC"),
            "lead_h": pl.Int32,
            "t2m_c": pl.Float64,
        },
    )


# --- max-of-trajectory anchor -------------------------------------------------

def test_anchor_takes_windowed_max_from_single_causal_run():
    """The causal 18:00 run rises across the window; anchor = its max, not the CP value."""
    run = _utc(2024, 1, 10, 18)  # <= cp(23) - 60min cutoff(22) -> causal
    rows = [
        {"model": "ecmwf_ifs_hres", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 10, 22), "t2m_c": 16.0},
        {"model": "ecmwf_ifs_hres", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 10, 23), "t2m_c": 17.5},
        {"model": "ecmwf_ifs_hres", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 11, 0), "t2m_c": 19.0},
        {"model": "ecmwf_ifs_hres", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 11, 1), "t2m_c": 18.0},
    ]
    cp = _utc(2024, 1, 10, 23)
    res = select_max_trajectory_anchor(
        _snapshots(rows), cp_utc=cp,
        window_start_utc=_utc(2024, 1, 10, 22), window_end_utc=_utc(2024, 1, 11, 1),
        models=["ecmwf_ifs_hres"],
    )
    assert res.nwp_t2m_maxtraj_c == 19.0  # the peak across the window
    assert res.per_model_max["ecmwf_ifs_hres"] == 19.0
    assert res.run_time_utc == run
    assert res.valid_time_utc == _utc(2024, 1, 11, 0)
    assert res.lead_h == 6
    assert res.n_models == 1
    assert res.n_valid_steps == 4


def test_anchor_ensemble_mean_and_spread():
    run = _utc(2024, 1, 10, 18)
    rows = [
        {"model": "ecmwf_ifs_hres", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 11, 0), "t2m_c": 20.0},
        {"model": "ncep_gfs_global", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 11, 0), "t2m_c": 18.0},
    ]
    cp = _utc(2024, 1, 10, 23)
    res = select_max_trajectory_anchor(
        _snapshots(rows), cp_utc=cp,
        window_start_utc=_utc(2024, 1, 10, 22), window_end_utc=_utc(2024, 1, 11, 1),
        models=["ecmwf_ifs_hres", "ncep_gfs_global"],
    )
    assert res.nwp_t2m_maxtraj_c == 19.0  # mean(20, 18)
    assert res.nwp_t2m_maxtraj_spread_c == pytest.approx(1.0)  # std(20,18)=1
    assert res.n_models == 2


def test_anchor_refuses_non_causal_run():
    """Only a too-fresh run exists (issued after the cutoff) -> no anchor, no leak."""
    run = _utc(2024, 1, 11, 0)  # 00:00 next day > cutoff 22:00 -> non-causal
    rows = [
        {"model": "ecmwf_ifs_hres", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 11, 0), "t2m_c": 25.0},
        {"model": "ecmwf_ifs_hres", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 11, 1), "t2m_c": 26.0},
    ]
    cp = _utc(2024, 1, 10, 23)
    res = select_max_trajectory_anchor(
        _snapshots(rows), cp_utc=cp,
        window_start_utc=_utc(2024, 1, 10, 22), window_end_utc=_utc(2024, 1, 11, 1),
        models=["ecmwf_ifs_hres"],
    )
    assert res.nwp_t2m_maxtraj_c is None
    assert res.run_time_utc is None
    assert res.valid_time_utc is None
    assert res.lead_h is None
    assert res.per_model_max["ecmwf_ifs_hres"] is None


def test_anchor_prefers_latest_causal_run_only():
    """Given an old causal run AND a fresh non-causal run, only the causal run feeds the max."""
    causal = _utc(2024, 1, 10, 18)
    fresh = _utc(2024, 1, 11, 0)  # non-causal
    rows = [
        {"model": "ecmwf_ifs_hres", "run_time_utc": causal, "valid_time_utc": _utc(2024, 1, 11, 0), "t2m_c": 19.0},
        {"model": "ecmwf_ifs_hres", "run_time_utc": fresh, "valid_time_utc": _utc(2024, 1, 11, 0), "t2m_c": 30.0},
    ]
    cp = _utc(2024, 1, 10, 23)
    res = select_max_trajectory_anchor(
        _snapshots(rows), cp_utc=cp,
        window_start_utc=_utc(2024, 1, 10, 22), window_end_utc=_utc(2024, 1, 11, 1),
        models=["ecmwf_ifs_hres"],
    )
    # 30.0 belongs to the non-causal run and must be ignored.
    assert res.nwp_t2m_maxtraj_c == 19.0


def test_anchor_window_excludes_out_of_range_valids():
    run = _utc(2024, 1, 10, 18)
    rows = [
        {"model": "ecmwf_ifs_hres", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 10, 20), "t2m_c": 99.0},  # before window
        {"model": "ecmwf_ifs_hres", "run_time_utc": run, "valid_time_utc": _utc(2024, 1, 10, 23), "t2m_c": 17.0},
    ]
    cp = _utc(2024, 1, 10, 23)
    res = select_max_trajectory_anchor(
        _snapshots(rows), cp_utc=cp,
        window_start_utc=_utc(2024, 1, 10, 22), window_end_utc=_utc(2024, 1, 11, 1),
        models=["ecmwf_ifs_hres"],
    )
    assert res.nwp_t2m_maxtraj_c == 17.0  # the 20:00/99.0 row is outside the window


def test_anchor_rejects_naive_datetimes():
    rows = [{"model": "ecmwf_ifs_hres", "run_time_utc": _utc(2024, 1, 10, 18),
             "valid_time_utc": _utc(2024, 1, 11, 0), "t2m_c": 19.0}]
    with pytest.raises(ValueError):
        select_max_trajectory_anchor(
            _snapshots(rows), cp_utc=datetime(2024, 1, 10, 23),  # naive
            window_start_utc=_utc(2024, 1, 10, 22), window_end_utc=_utc(2024, 1, 11, 1),
            models=["ecmwf_ifs_hres"],
        )


# --- Tmax-hour climatology ----------------------------------------------------

def _labels_with_tmax_hour(start: date, end: date, *, peak_local_h: int, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    tz = timezone.utc  # store local stamps as UTC-tagged for the test (tz arithmetic not exercised here)
    dates, stamps = [], []
    d = start
    while d <= end:
        dates.append(d)
        jitter_min = int(rng.integers(-90, 90))
        stamps.append(
            datetime(d.year, d.month, d.day, peak_local_h, 0, tzinfo=tz) + timedelta(minutes=jitter_min)
        )
        d = d + timedelta(days=1)
    return pl.DataFrame(
        {
            "date_local": dates,
            "day_complete": [True] * len(dates),
            "tmax_ts_local": stamps,
        },
        schema={
            "date_local": pl.Date,
            "day_complete": pl.Boolean,
            "tmax_ts_local": pl.Datetime("us", time_zone="UTC"),
        },
    )


def test_tmax_hour_climatology_centers_on_peak_hour():
    labels = _labels_with_tmax_hour(date(2020, 1, 1), date(2022, 12, 31), peak_local_h=14)
    thc = fit_tmax_hour_climatology(
        labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name="UTC"
    )
    lo, hi = thc.window_local_hours(date(2023, 1, 15))
    assert lo < 14.0 < hi
    # +-90min jitter -> 10/90 quantiles within ~1.5h of the 14:00 peak.
    assert 12.0 <= lo <= 14.0
    assert 14.0 <= hi <= 16.0


def test_tmax_hour_regime_conditioning_is_refused_until_gmm_exists():
    labels = _labels_with_tmax_hour(date(2020, 1, 1), date(2022, 12, 31), peak_local_h=14)
    thc = fit_tmax_hour_climatology(
        labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name="UTC"
    )
    with pytest.raises(NotImplementedError, match="regime"):
        thc.window_local_hours(date(2023, 1, 15), regime=3)


def test_tmax_hour_window_utc_is_tz_aware_and_ordered():
    labels = _labels_with_tmax_hour(date(2020, 1, 1), date(2022, 12, 31), peak_local_h=14)
    thc = fit_tmax_hour_climatology(
        labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name="UTC"
    )
    cp = _utc(2023, 1, 15, 23)
    start, end = thc.window_utc(date(2023, 1, 15), cp)
    assert start.tzinfo is not None and end.tzinfo is not None
    assert start < end
