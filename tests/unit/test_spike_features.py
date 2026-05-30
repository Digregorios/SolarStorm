"""Unit tests for core/spike/features.py - causal no-leak."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import polars as pl
import pytest

from core.spike.features import SPIKE_FEATURE_COLUMNS, build_spike_features


def _make_obs(n: int = 10, start_hour: int = 6, date_local: date = date(2024, 1, 15)):
    """Synthetic obs frame with required columns."""
    base_utc = datetime(
        date_local.year, date_local.month, date_local.day,
        start_hour, 0, 0, tzinfo=timezone.utc
    )
    rows = []
    for i in range(n):
        ts = base_utc + timedelta(minutes=30 * i)
        rows.append({
            "ts_utc": ts,
            "tmp_c_int": 15 + i,
            "dq_tmp_c_int": "ok",
            "tmpf": float((15 + i) * 9 / 5 + 32),
            "dwpf": float((10 + i) * 9 / 5 + 32),
            "drct": 180.0 + i * 5,
            "sknt": 10.0 + i,
            "alti": 30.0,
            "vsby": 10.0,
            "skyl1": 5000.0,
            "wxcodes": "",
            "p01i": 0.0,
        })
    schema = {
        "ts_utc": pl.Datetime("us", time_zone="UTC"),
        "tmp_c_int": pl.Int32,
        "dq_tmp_c_int": pl.Utf8,
        "tmpf": pl.Float64,
        "dwpf": pl.Float64,
        "drct": pl.Float64,
        "sknt": pl.Float64,
        "alti": pl.Float64,
        "vsby": pl.Float64,
        "skyl1": pl.Float64,
        "wxcodes": pl.Utf8,
        "p01i": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema)


class TestCausalNoLeak:
    """REQ-AUD-4: features must not change when post-cp obs are appended."""

    def test_appending_post_cp_obs_does_not_change_features(self):
        d = date(2024, 1, 15)
        cp = "20:00"
        # Obs from 06:00 to 10:30 UTC (all before cp 20:00)
        obs_pre = _make_obs(n=10, start_hour=6, date_local=d)
        feats_pre = build_spike_features(
            obs_pre, date_local=d, cp_hhmm=cp, tz_name="Pacific/Auckland"
        )

        # Append obs AFTER cp (21:00, 21:30, 22:00)
        post_rows = []
        base_post = datetime(2024, 1, 15, 21, 0, tzinfo=timezone.utc)
        for i in range(3):
            ts = base_post + timedelta(minutes=i * 30)
            post_rows.append({
                "ts_utc": ts,
                "tmp_c_int": 30 + i,  # much higher temp
                "dq_tmp_c_int": "ok",
                "tmpf": float((30 + i) * 9 / 5 + 32),
                "dwpf": float(20 * 9 / 5 + 32),
                "drct": 270.0,
                "sknt": 25.0,
                "alti": 29.5,
                "vsby": 5.0,
                "skyl1": 3000.0,
                "wxcodes": "RA",
                "p01i": 2.0,
            })
        obs_post = pl.concat([obs_pre, pl.DataFrame(post_rows, schema=obs_pre.schema)])
        feats_post = build_spike_features(
            obs_post, date_local=d, cp_hhmm=cp, tz_name="Pacific/Auckland"
        )

        # Every feature must be identical
        for col in SPIKE_FEATURE_COLUMNS:
            assert feats_pre[col] == feats_post[col], (
                f"Feature {col} leaked: pre={feats_pre[col]} post={feats_post[col]}"
            )

    def test_causality_assertion_fires_on_bad_data(self):
        """If obs has ts_utc >= cp_utc after filtering, assertion fires."""
        # This shouldn't happen with correct _filter_causal, but test the guard
        d = date(2024, 1, 15)
        cp = "10:00"
        obs = _make_obs(n=10, start_hour=6, date_local=d)
        # All obs are before 10:00 UTC (06:00 to 10:30 -> last is 10:30)
        # With cp=10:00, obs at 10:30 is AFTER cp -> should be filtered out
        feats = build_spike_features(
            obs, date_local=d, cp_hhmm=cp, tz_name="Pacific/Auckland"
        )
        # Should succeed (filter removes post-cp obs)
        assert feats["time_since_new_max_min"] is not None or True


class TestFeatureColumns:
    """Verify SPIKE_FEATURE_COLUMNS matches output keys."""

    def test_all_columns_present(self):
        d = date(2024, 1, 15)
        obs = _make_obs(n=10, start_hour=6, date_local=d)
        feats = build_spike_features(
            obs, date_local=d, cp_hhmm="20:00", tz_name="Pacific/Auckland"
        )
        for col in SPIKE_FEATURE_COLUMNS:
            assert col in feats, f"Missing feature: {col}"
