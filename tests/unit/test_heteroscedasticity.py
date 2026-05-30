"""Unit tests for the Phase 5 heteroscedasticity coverage gate (T-5-3, REQ-AUD-5)."""

from __future__ import annotations

import numpy as np
import pytest

from core.contracts.phase5 import (
    HETEROSCED_COVERAGE_HIGH,
    HETEROSCED_COVERAGE_LOW,
    HETEROSCED_N_BINS,
)
from core.eval.gates_phase5 import (
    HeteroscedasticityReport,
    heteroscedasticity_gate,
)


def _intervals_with_coverage(rng, half_width, n, target_cov, center=20):
    """Build IC80 rows of fixed half-width with a controlled empirical coverage.

    Returns (lo, hi, y_true). ``target_cov`` of the rows land inside the bracket;
    the rest are pushed one bracket beyond the high edge so they are uncovered.
    """
    lo = np.full(n, center - half_width, dtype=int)
    hi = np.full(n, center + half_width, dtype=int)
    n_cov = int(round(target_cov * n))
    y = np.empty(n, dtype=int)
    y[:n_cov] = center  # inside [lo, hi]
    y[n_cov:] = hi[n_cov:] + 1  # outside
    perm = rng.permutation(n)
    return lo, hi, y[perm]


def test_homoscedastic_well_calibrated_passes():
    rng = np.random.default_rng(42)
    # Roughly constant widths (3 or 4 brackets), ~80% coverage everywhere.
    los, his, ys = [], [], []
    for hw in (1, 1, 2, 2):
        lo, hi, y = _intervals_with_coverage(rng, hw, 200, 0.80)
        los.append(lo)
        his.append(hi)
        ys.append(y)
    lo = np.concatenate(los)
    hi = np.concatenate(his)
    yt = np.concatenate(ys)

    rep = heteroscedasticity_gate(lo, hi, yt)
    assert isinstance(rep, HeteroscedasticityReport)
    assert rep.passed is True
    assert rep.mixed_in_and_out is False
    assert all(HETEROSCED_COVERAGE_LOW <= b.coverage <= HETEROSCED_COVERAGE_HIGH for b in rep.bins)


def test_heteroscedastic_miscalibration_fails_and_is_mixed():
    rng = np.random.default_rng(42)
    # Narrow bin (half_width 0 -> width 1) badly UNDER-covers (50% < 0.70);
    # wide bin (half_width 5 -> width 11) sits inside band at ~80%.
    lo_n, hi_n, y_n = _intervals_with_coverage(rng, 0, 300, 0.50)
    lo_w, hi_w, y_w = _intervals_with_coverage(rng, 5, 300, 0.80)
    lo = np.concatenate([lo_n, lo_w])
    hi = np.concatenate([hi_n, hi_w])
    yt = np.concatenate([y_n, y_w])

    rep = heteroscedasticity_gate(lo, hi, yt, n_bins=2)
    assert rep.passed is False
    assert rep.mixed_in_and_out is True
    # The narrowest bin should be the under-covering one.
    narrow = min(rep.bins, key=lambda b: b.mean_width)
    assert narrow.coverage < HETEROSCED_COVERAGE_LOW


def test_degenerate_identical_widths_no_crash():
    rng = np.random.default_rng(42)
    # All rows share width 3; well-calibrated ~80%.
    lo, hi, yt = _intervals_with_coverage(rng, 1, 400, 0.80)
    rep = heteroscedasticity_gate(lo, hi, yt)
    assert isinstance(rep, HeteroscedasticityReport)
    assert rep.n == 400
    assert rep.n_bins == HETEROSCED_N_BINS
    # Only one distinct width -> a single non-empty bin.
    assert len(rep.bins) == 1
    assert rep.bins[0].width_lo == rep.bins[0].width_hi == 3.0
    assert rep.passed is True

    # Determinism: identical inputs -> identical report.
    rep2 = heteroscedasticity_gate(lo, hi, yt)
    assert rep == rep2


def test_input_validation_raises():
    with pytest.raises(ValueError):
        heteroscedasticity_gate([0, 1], [2, 3, 4], [1, 1, 1])  # mismatched lengths
    with pytest.raises(ValueError):
        heteroscedasticity_gate([], [], [])  # empty
