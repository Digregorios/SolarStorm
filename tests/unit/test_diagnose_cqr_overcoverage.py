"""Unit pins for the pure D1-D6 diagnostic helpers (scripts/diagnose_cqr_overcoverage.py).

Closed-form / constructed checks only -- the full real-data diagnostic is a script
entry point and is NOT run here (mirrors the eval script staying out of the suite).
This keeps the anti-gaming discipline: the helpers are verified on inputs with known
answers, independent of the panel.
"""

from __future__ import annotations

import numpy as np

from scripts.diagnose_cqr_overcoverage import (
    crossing_frequency,
    marginal_fixed_window_width_80,
    pinball_loss,
    width_attribution,
)


def test_pinball_loss_closed_form():
    # Single point, q below y: loss = alpha * (y - q).
    assert pinball_loss(np.array([0.0]), np.array([10.0]), 0.10) == 0.10 * 10.0
    # q above y: loss = (1 - alpha) * (q - y) = (alpha - 1) * (y - q).
    assert pinball_loss(np.array([10.0]), np.array([0.0]), 0.90) == (1 - 0.90) * 10.0
    # Perfect prediction -> 0.
    assert pinball_loss(np.array([5.0]), np.array([5.0]), 0.5) == 0.0


def test_pinball_loss_symmetry_at_median():
    # At alpha=0.5 the loss is symmetric in over/under prediction.
    over = pinball_loss(np.array([7.0]), np.array([5.0]), 0.5)
    under = pinball_loss(np.array([3.0]), np.array([5.0]), 0.5)
    assert over == under == 0.5 * 2.0


def test_crossing_frequency_counts_inverted_pairs():
    raw_lo = np.array([1.0, 5.0, 2.0, 3.0])
    raw_hi = np.array([2.0, 4.0, 3.0, 1.0])  # rows 1 and 3 are crossed (lo > hi)
    assert crossing_frequency(raw_lo, raw_hi) == 0.5
    # No crossings.
    assert crossing_frequency(np.array([1.0, 2.0]), np.array([3.0, 4.0])) == 0.0


def test_marginal_fixed_window_width_80_known_answer():
    # y uniformly on integers 0..9 (n=10): need >=8 covered. The tightest window
    # covering 8 of the 10 distinct integers spans 8 brackets (e.g. [0,7] or [2,9]).
    y = np.arange(0, 10)
    assert marginal_fixed_window_width_80(y) == 8
    # All identical -> a single bracket covers everything.
    assert marginal_fixed_window_width_80(np.array([5, 5, 5, 5, 5])) == 1


def test_marginal_fixed_window_width_80_concentrated_mass():
    # 9 values at 5, one outlier at 50: a width-1 window at 5 covers 90% >= 80%.
    y = np.array([5] * 9 + [50])
    assert marginal_fixed_window_width_80(y) == 1


def test_width_attribution_arithmetic():
    # base band width 3 (0..2 -> 3 brackets); CQR band width 5 (-1..3 -> 5 brackets).
    base_lo = np.array([0.0, 0.0])
    base_hi = np.array([2.0, 2.0])
    cqr_lo = np.array([-1, -1])
    cqr_hi = np.array([3, 3])
    out = width_attribution(base_lo, base_hi, cqr_lo, cqr_hi)
    assert out["mean_base_width"] == 3.0
    assert out["mean_cqr_width"] == 5.0
    assert out["cqr_added_width"] == 2.0
    assert out["cqr_width_fraction"] == 0.4  # 2 / 5
