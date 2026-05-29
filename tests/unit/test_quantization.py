"""Quantization Q(x), support_K and band-aware loss/softmax tests."""

from __future__ import annotations

import math

from core.baselines.support import support_K
from core.contracts.quantization import B, Q, distance_to_band, in_band
from core.models.loss import band_aware_loss, latent_to_prob_dist


def test_Q_round_half_up():
    assert Q(18.49) == 18
    assert Q(18.50) == 19
    assert Q(-0.5) == 0
    assert Q(-0.51) == -1


def test_B_consistent_with_Q():
    for k in range(-10, 41):
        low, high = B(k)
        assert Q(low) == k
        assert Q(low + 0.4999) == k
        # high is the *next* band's lower bound
        assert Q(high) == k + 1


def test_in_band_and_distance():
    assert in_band(18.0, 18) is True
    assert in_band(18.5, 18) is False
    assert in_band(18.5, 19) is True
    assert distance_to_band(18.0, 18) == 0.0
    assert distance_to_band(20.0, 18) == 1.5
    assert distance_to_band(15.0, 18) == 2.5


def test_support_K_climo_only():
    sk = support_K(15.0, 25.0)
    assert sk[0] == 13
    assert sk[-1] == 27


def test_support_K_truncated():
    sk = support_K(-15.0, 50.0, tmp_min=-10, tmp_max=40)
    assert sk[0] == -10
    assert sk[-1] == 40


def test_band_aware_loss_zero_inside():
    assert band_aware_loss(18.2, 18) == 0.0
    assert band_aware_loss(18.499, 18) == 0.0


def test_band_aware_loss_outside_linear():
    assert band_aware_loss(20.0, 18, mode="linear") == 1.5
    assert band_aware_loss(20.0, 18, mode="quadratic") == 1.5 ** 2


def test_latent_to_prob_dist_normalises_and_peaks_at_truth():
    sk = list(range(15, 23))
    dist = latent_to_prob_dist(18.4, sk, tau=0.5, mode="linear")
    assert math.isclose(sum(dist.values()), 1.0, abs_tol=1e-9)
    # Peak should be at k=18 (closest band)
    peak = max(dist.items(), key=lambda kv: kv[1])[0]
    assert peak == 18
