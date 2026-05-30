"""Panel wiring for the max-of-trajectory anchor (design 4.5.2.1, GFS s3_grib).

Pins that build_training_panel, when given a TmaxHourClimatology, anchors on the
windowed max of the causal run (nwp_t2m_maxtraj_c) and leaves the single-hour-at-CP
value as a feature only. Without the climatology (Phase 3 path) the column is absent.

Times use a winter local date (NZST = UTC+12, no DST). cp_to_utc resolves the CP via
Pacific/Auckland, so CP 23:00 for local 2024-07-10 lands at 2024-07-09 23:00 UTC and
the forward Tmax window (local 12-16h) maps to 2024-07-10 00:00..04:00 UTC.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl

from core.baselines.climatology import Climatology, TmaxHourClimatology
from core.features.training_panel import build_training_panel

_D = date(2024, 7, 10)
_TZ = "Pacific/Auckland"
_GFS = "ncep_gfs_global"
_RUN = datetime(2024, 7, 9, 18, 0, tzinfo=timezone.utc)  # causal (<= cp-60min = 22:00)


def _dt(y, mo, d, hh):
    return datetime(y, mo, d, hh, 0, tzinfo=timezone.utc)


def _obs():
    rows = [(_dt(2024, 7, 9, h), 8 + h % 3, "ok") for h in range(13, 23)]
    return pl.DataFrame(
        {
            "ts_utc": pl.Series([r[0] for r in rows], dtype=pl.Datetime("us", time_zone="UTC")),
            "tmp_c_int": pl.Series([r[1] for r in rows], dtype=pl.Int32),
            "dq_tmp_c_int": pl.Series([r[2] for r in rows], dtype=pl.Utf8),
        }
    )


def _labels():
    return pl.DataFrame(
        {"date_local": [_D], "tmax_int": [12], "tmin_int": [6], "day_complete": [True]}
    )


def _climo():
    return Climatology(
        by_doy={}, by_month={7: {"mean": 10.0}}, train_window=(_D, _D), n_train_days=1
    )


def _thc():
    return TmaxHourClimatology(
        by_month={7: {"center_h": 14.0, "lo_h": 12.0, "hi_h": 16.0, "n": 100.0}},
        tz_name=_TZ,
        train_window=(_D, _D),
    )


def _snaps():
    # All rows from the single causal 18Z run. at-CP (23:00 UTC) = 13.0; the forward
    # window 00:00..04:00 UTC peaks at 18.0 (01:00).
    pts = [
        (_dt(2024, 7, 9, 23), 5, 13.0),
        (_dt(2024, 7, 10, 0), 6, 16.0),
        (_dt(2024, 7, 10, 1), 7, 18.0),
        (_dt(2024, 7, 10, 2), 8, 17.0),
        (_dt(2024, 7, 10, 3), 9, 15.0),
        (_dt(2024, 7, 10, 4), 10, 14.0),
    ]
    return pl.DataFrame(
        {
            "model": [_GFS] * len(pts),
            "run_time_utc": pl.Series([_RUN] * len(pts), dtype=pl.Datetime("us", time_zone="UTC")),
            "valid_time_utc": pl.Series([p[0] for p in pts], dtype=pl.Datetime("us", time_zone="UTC")),
            "lead_h": pl.Series([p[1] for p in pts], dtype=pl.Int32),
            "t2m_c": pl.Series([p[2] for p in pts], dtype=pl.Float64),
        }
    )


def test_panel_anchors_on_windowed_max_from_causal_run():
    panel = build_training_panel(
        _obs(), _labels(), climo=_climo(), tz_name=_TZ, cp_set=["23:00"],
        dates=[_D], nwp_snapshots=_snaps(), nwp_models=(_GFS,), tmax_hour_climo=_thc(),
    )
    row = panel.row(0, named=True)
    assert row["nwp_t2m_maxtraj_c"] == 18.0          # windowed max of the causal run
    assert row["nwp_t2m_maxtraj_spread_c"] == 0.0    # single model
    assert row["nwp_t2m_at_cp_c"] == 13.0            # single-hour-at-CP stays a feature
    assert row["nwp_run_time_utc"] == _RUN


def test_panel_without_climo_has_no_maxtraj_column():
    panel = build_training_panel(
        _obs(), _labels(), climo=_climo(), tz_name=_TZ, cp_set=["23:00"],
        dates=[_D], nwp_snapshots=_snaps(), nwp_models=(_GFS,),
    )
    assert "nwp_t2m_maxtraj_c" not in panel.columns
