"""Tests for scripts/evaluate_recent_holdout_backtest.py."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import evaluate_recent_holdout_backtest as holdout


def _obs(start: date, n_days: int) -> pl.DataFrame:
    rows = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        for h in (0, 6, 12, 18):
            ts = datetime(d.year, d.month, d.day, h, 0, tzinfo=timezone.utc)
            tmp = 10 + i
            rows.append((ts, tmp))
    return pl.DataFrame(
        {
            "ts_utc": [r[0] for r in rows],
            "tmp_c_int": [r[1] for r in rows],
            "dq_tmp_c_int": ["ok"] * len(rows),
            "tmpf": [float(r[1]) * 9.0 / 5.0 + 32.0 for r in rows],
            "drct": [180.0] * len(rows),
            "sknt": [10.0] * len(rows),
            "alti": [29.9] * len(rows),
        }
    )


def _labels(dates: list[date], complete: list[bool]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date_local": dates,
            "tmax_int": [15 + i for i in range(len(dates))],
            "tmin_int": [10 + i for i in range(len(dates))],
            "day_complete": complete,
        },
        schema_overrides={
            "date_local": pl.Date,
            "tmax_int": pl.Int32,
            "tmin_int": pl.Int32,
            "day_complete": pl.Boolean,
        },
    )


def test_recent_holdout_uses_base_complete_cutoff_and_eval_complete_truth(monkeypatch, tmp_path):
    base_dates = [date(2026, 5, 26), date(2026, 5, 27)]
    eval_dates = base_dates + [date(2026, 5, 28), date(2026, 5, 29), date(2026, 5, 30)]
    base_obs = _obs(date(2026, 5, 26), 2)
    eval_obs = _obs(date(2026, 5, 26), 5)

    def fake_load(path, **kwargs):
        stats = SimpleNamespace(fallback_rate=0.0)
        if "base" in str(path):
            return base_obs, stats
        return eval_obs, stats

    def fake_labels(obs, **kwargs):
        if obs.height == base_obs.height:
            return _labels(base_dates, [True, True])
        # 2026-05-30 is incomplete and must not enter truth rows.
        return _labels(eval_dates, [True, True, True, True, False])

    class Cfg:
        icao = "NZWN"
        tz = "UTC"
        cp_set_utc = ["20:00"]

        class tmp_c_int_plausibility:
            min = -10
            max = 40

    monkeypatch.setattr(holdout, "load_station_config", lambda _: Cfg())
    monkeypatch.setattr(holdout, "load_observations", fake_load)
    monkeypatch.setattr(holdout, "build_tmax_labels", fake_labels)

    class FakeClimo:
        def percentiles_for(self, d):
            return (10.0, 20.0)

        def tmax_dec_for(self, d):
            return 15.0

    monkeypatch.setattr(holdout, "fit_climatology", lambda *a, **kw: FakeClimo())

    report = holdout.evaluate_recent_holdout(
        station_yaml=Path("station.yaml"),
        base_csv=Path("base.csv"),
        eval_csv=Path("eval.csv"),
        train_start=date(2026, 5, 26),
        train_end=None,
        holdout_start=None,
        holdout_end=None,
        cp_set=("20:00",),
    )

    assert report["config"]["train_end"] == "2026-05-27"
    assert report["config"]["holdout_start"] == "2026-05-28"
    assert report["config"]["holdout_end"] == "2026-05-29"
    assert report["data_windows"]["holdout_complete_days"] == 2
    assert {r["date_local"] for r in report["rows"]} == {"2026-05-28", "2026-05-29"}
    assert set(report["metrics"]["per_date"]) == {"2026-05-28", "2026-05-29"}
    assert "empirical" in report["metrics"]["wins_by_date_mae"]
    assert report["config"]["empirical_n_min_bucket"] == 30
    assert all("empirical_bucket_n" in r for r in report["rows"])
    assert all("empirical_marginal_n" in r for r in report["rows"])


def test_aligned_rps_handles_truth_outside_prediction_support():
    assert holdout._aligned_rps({10: 1.0}, 12) > 0.0
    assert holdout._aligned_rps({12: 1.0}, 12) == 0.0
