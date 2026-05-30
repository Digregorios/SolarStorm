"""Causal-climatology audit (review D1).

The Phase-3/4 training panel seeds ``clim_tmax_c_dec`` ONCE from a broad
climatology fit over 2020-2024 - a span that includes the 2023/2024/2025 test
years. Feeding that column into a model FEATURE leaks the test distribution into
training. ``_evaluate_split`` must rebuild the column from a per-split
TRAIN-ONLY climo, and ``assert_causal_climo`` guards against a future regression
that forgets to. These tests fail if a panel feature is derived from a
climatology whose train window overlaps the rows it is applied to.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from core.baselines.climatology import Climatology, fit_climatology
from core.features.training_panel import FEATURE_COLUMNS
from scripts.phase4_evaluate import (
    CLIMO_DERIVED_FEATURES,
    CausalClimatologyError,
    _rebuild_climo_features,
    assert_causal_climo,
)


def _climo_with_window(train_start: date, train_end: date, *, mean: float = 15.0) -> Climatology:
    """A minimal Climatology with a known train window for guard tests."""
    return Climatology(
        by_doy={doy: {"mean": mean} for doy in range(1, 367)},
        by_month={
            m: {"mean": mean, "p10": mean - 3, "p50": mean, "p90": mean + 3}
            for m in range(1, 13)
        },
        train_window=(train_start, train_end),
        n_train_days=365,
    )


def _synthetic_labels(start: date, end: date, *, seed: int = 0) -> pl.DataFrame:
    """Daily labels with a seasonal signal so fit_climatology has structure."""
    rng = np.random.default_rng(seed)
    days: list[date] = []
    d = start
    while d <= end:
        days.append(d)
        d = d + timedelta(days=1)
    tmax = []
    for day in days:
        doy = day.timetuple().tm_yday
        seasonal = 15.0 + 8.0 * np.sin(2 * np.pi * (doy - 30) / 365.0)
        tmax.append(int(round(seasonal + rng.normal(0, 1.5))))
    return pl.DataFrame(
        {"date_local": days, "tmax_int": tmax, "day_complete": [True] * len(days)}
    )


def test_climo_derived_features_are_real_panel_features():
    """The guarded list must be a subset of the columns X actually consumes,
    otherwise the audit guards a phantom and the real leak slips through."""
    assert set(CLIMO_DERIVED_FEATURES) <= set(FEATURE_COLUMNS)
    assert "clim_tmax_c_dec" in CLIMO_DERIVED_FEATURES


def test_assert_causal_climo_passes_when_disjoint():
    climo = _climo_with_window(date(2020, 1, 1), date(2022, 12, 31))
    test_dates = [date(2023, 1, 1), date(2023, 6, 15), date(2023, 12, 31)]
    assert_causal_climo(climo, test_dates)  # must not raise


def test_assert_causal_climo_raises_on_overlap():
    climo = _climo_with_window(date(2020, 1, 1), date(2024, 12, 31))
    test_dates = [date(2023, 1, 1), date(2023, 6, 15)]  # inside the broad window
    with pytest.raises(CausalClimatologyError, match="overlap"):
        assert_causal_climo(climo, test_dates)


def test_assert_causal_climo_raises_on_inclusive_boundary():
    """train_end itself counts as overlap (the climo saw that day)."""
    climo = _climo_with_window(date(2020, 1, 1), date(2022, 12, 31))
    with pytest.raises(CausalClimatologyError):
        assert_causal_climo(climo, [date(2022, 12, 31)])


def test_rebuild_overwrites_leaked_feature_with_causal_values():
    """A broad climo (leaky) and a train-only climo produce different feature
    values on the test rows; rebuild must install the train-only values, and the
    broad-climo guard must reject those same rows."""
    broad = fit_climatology(
        _synthetic_labels(date(2020, 1, 1), date(2024, 12, 31)),
        train_start=date(2020, 1, 1),
        train_end=date(2024, 12, 31),
    )
    causal = fit_climatology(
        _synthetic_labels(date(2020, 1, 1), date(2022, 12, 31)),
        train_start=date(2020, 1, 1),
        train_end=date(2022, 12, 31),
    )
    test_dates = [date(2023, 1, 10) + timedelta(days=30 * i) for i in range(6)]
    leaked = [float(broad.tmax_dec_for(d)) for d in test_dates]
    panel = pl.DataFrame(
        {"date_local": test_dates, "clim_tmax_c_dec": leaked}
    )

    # The broad climo would leak; the guard catches it on these very rows.
    with pytest.raises(CausalClimatologyError):
        assert_causal_climo(broad, test_dates)
    # The causal climo is disjoint from the test rows -> safe.
    assert_causal_climo(causal, test_dates)

    rebuilt = _rebuild_climo_features(panel, causal)
    expected = [float(causal.tmax_dec_for(d)) for d in test_dates]
    assert rebuilt["clim_tmax_c_dec"].to_list() == expected
    # And it actually changed something (the two climos disagree somewhere).
    assert rebuilt["clim_tmax_c_dec"].to_list() != leaked


def test_rebuild_preserves_other_columns_and_row_order():
    causal = fit_climatology(
        _synthetic_labels(date(2020, 1, 1), date(2022, 12, 31)),
        train_start=date(2020, 1, 1),
        train_end=date(2022, 12, 31),
    )
    test_dates = [date(2023, 3, 1), date(2023, 3, 2), date(2023, 3, 3)]
    panel = pl.DataFrame(
        {
            "date_local": test_dates,
            "clim_tmax_c_dec": [99.0, 99.0, 99.0],
            "k_cp": [10, 11, 12],
        }
    )
    rebuilt = _rebuild_climo_features(panel, causal)
    assert rebuilt["date_local"].to_list() == test_dates
    assert rebuilt["k_cp"].to_list() == [10, 11, 12]
    assert rebuilt["clim_tmax_c_dec"].to_list() != [99.0, 99.0, 99.0]
