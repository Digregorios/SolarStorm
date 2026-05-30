"""Horizon-degradation curve helper (design 28.6).

The curve reports bracket-match skill per evaluation CP (a lead-to-peak proxy) for
obs-only vs obs+NWP, so a reviewer can see whether NWP forward skill holds hours
before the Tmax peak (genuine) or only at the CP glued to the peak (nowcasting). It
is a REPORTED diagnostic with no committed threshold, so these tests pin its shape
and arithmetic, not any pass/fail bar.
"""

from __future__ import annotations

import numpy as np

from scripts.phase4_evaluate import horizon_degradation_curve


CP_SET = ["20:00", "21:00", "22:00", "23:00"]


def test_one_entry_per_present_cp_in_cp_set_order():
    # 21:00 is absent from the rows -> it must be skipped, and the surviving entries
    # must follow cp_set order regardless of row order.
    cp_values = ["23:00", "20:00", "22:00", "20:00", "23:00"]
    y = np.array([10, 11, 12, 11, 13])
    full = np.array([10, 11, 12, 11, 13])  # exact -> all hits
    obs = np.array([10, 11, 12, 11, 13])
    curve = horizon_degradation_curve(cp_values, y, full, obs, CP_SET)
    assert [c["cp"] for c in curve] == ["20:00", "22:00", "23:00"]
    assert sum(c["n"] for c in curve) == 5
    for c in curve:
        assert set(c) == {"cp", "n", "bm_obs_only", "bm_obs_plus_nwp", "nwp_delta"}


def test_delta_positive_when_nwp_beats_obs_only():
    # obs+NWP exact (bracket-match 1.0); obs-only far off (bracket-match 0.0).
    # bracket_match_at_p50 is exact-integer match, so any nonzero error is a miss.
    cp_values = ["23:00"] * 4
    y = np.array([10, 10, 10, 10])
    full = np.array([10, 10, 10, 10])
    obs = np.array([17, 17, 17, 17])
    curve = horizon_degradation_curve(cp_values, y, full, obs, ["23:00"])
    assert len(curve) == 1
    c = curve[0]
    assert c["n"] == 4
    assert c["bm_obs_plus_nwp"] == 1.0
    assert c["bm_obs_only"] == 0.0
    assert c["nwp_delta"] == 1.0


def test_delta_negative_when_nwp_worse():
    cp_values = ["22:00"] * 3
    y = np.array([5, 6, 7])
    full = np.array([0, 0, 0])  # all miss
    obs = np.array([5, 6, 7])  # exact
    curve = horizon_degradation_curve(cp_values, y, full, obs, ["22:00"])
    assert curve[0]["nwp_delta"] == -1.0


def test_empty_cp_set_yields_empty_curve():
    curve = horizon_degradation_curve(
        ["23:00"], np.array([1]), np.array([1]), np.array([1]), []
    )
    assert curve == []
