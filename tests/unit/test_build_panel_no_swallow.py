"""Tests that build_panel does NOT swallow causality / runtime errors (review #7)."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import core.features.builder as builder_mod
from core.features.builder import build_panel


def test_build_panel_propagates_runtime_error_from_build_cp_features(monkeypatch):
    """If build_cp_features raises (eg causality violation, out-of-window CP),
    build_panel must propagate the error instead of silently writing None."""
    boom_message = "synthetic causality violation"

    def boom(*args, **kwargs):
        raise RuntimeError(boom_message)

    monkeypatch.setattr(builder_mod, "build_cp_features", boom)

    obs = pl.DataFrame(
        {
            "ts_utc": pl.Series(
                [], dtype=pl.Datetime("us", time_zone="UTC")
            ),
            "tmp_c_int": pl.Series([], dtype=pl.Int32),
            "dq_tmp_c_int": pl.Series([], dtype=pl.Utf8),
        }
    )
    labels = pl.DataFrame(
        {
            "date_local": [date(2025, 1, 1)],
            "tmax_int": [20],
            "day_complete": [True],
        }
    )
    with pytest.raises(RuntimeError, match=boom_message):
        build_panel(obs, labels, tz_name="Pacific/Auckland", cp_set=["23:00"])
