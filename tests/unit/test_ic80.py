"""IC80 / discrete_ic regression tests (review #4)."""

from __future__ import annotations

import pytest

from core.eval.intervals import discrete_ic


def test_ic80_first_bin_already_crosses_10pct():
    """If sorted_k[0] alone already exceeds 10%, low must stay at sorted_k[0],
    not be silently overwritten on iteration 1 (the buggy pre-fix behaviour)."""
    pd = {15: 0.50, 16: 0.30, 17: 0.15, 18: 0.05}
    low, high = discrete_ic(pd)
    assert low == 15
    assert high == 17


def test_ic80_typical_distribution():
    pd = {9: 0.006, 10: 0.086, 11: 0.104, 12: 0.153, 13: 0.190,
          14: 0.221, 15: 0.129, 16: 0.067, 17: 0.044}
    low, high = discrete_ic(pd)
    assert low == 11
    assert high == 16


def test_ic80_degenerate_never_reaches_10pct():
    """Total mass below 10% (e.g., truncated bad distribution): low_set stays False
    and we keep the extremes."""
    pd = {15: 0.03, 16: 0.02, 17: 0.01}  # sum=0.06, never reaches 0.10
    low, high = discrete_ic(pd)
    assert low == 15
    assert high == 17


def test_ic80_rejects_invalid_percentiles():
    with pytest.raises(ValueError):
        discrete_ic({1: 1.0}, p_low=0.9, p_high=0.1)


def test_ic80_rejects_empty_dist():
    with pytest.raises(ValueError):
        discrete_ic({})


def test_ic50_works_with_custom_percentiles():
    pd = {1: 0.1, 2: 0.4, 3: 0.4, 4: 0.1}
    low, high = discrete_ic(pd, p_low=0.25, p_high=0.75)
    assert low == 2
    assert high == 3


def test_ic80_negative_temperatures():
    """Negative keys (frost days in Wellington) must sort and accumulate correctly."""
    pd = {-5: 0.10, -3: 0.20, -1: 0.30, 1: 0.25, 3: 0.10, 5: 0.05}
    low, high = discrete_ic(pd)
    # 10th percentile: -5 (0.10) -> low = -5
    # 90th percentile: need cumulative 0.90 -> -1:0.60, 1:0.85, 3:0.95 -> high = 3
    assert low == -5
    assert high == 3
