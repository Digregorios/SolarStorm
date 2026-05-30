"""Track P (predictive-distribution uncertainty sigma) - method + sanity unit tests.

Pre-registered in ``contracts/phase5_amendment_trackP_predictive_uncertainty.md``
(conformal_method_version 1.3). Covers the four areas the contract's test checklist
requires: entropy closed-form (incl. the one-hot ``H=0`` and uniform ``H=ln|K|`` corners),
the no-leak / determinism properties of the calib-frozen P1 floor wired into the v1.0
conformal path, the two MANDATORY pre-run sanity helpers (Spearman monotonicity + per-CP
distinct-count), and the reduction-to-fixed-width / collapsed-proxy detection path.
"""

from __future__ import annotations

import math

import numpy as np

from core.calibration.conformal import (
    NormalizedConformalConfig,
    _normalized_int_interval,
    _prepare_sigma,
    apply_normalized_conformal,
    fit_normalized_conformal,
)
from core.eval.sanity_trackP import (
    entropy_sigma_hat,
    monotonicity_sanity,
    per_cp_distinct_sanity,
    prob_dist_entropy,
    spearman_rho,
)


# --- entropy closed-form (nats; 0*ln0=0; raw, label-invariant) ----------------


def test_entropy_one_hot_is_zero():
    assert prob_dist_entropy({3: 1.0}) == 0.0
    assert prob_dist_entropy({3: 1.0, 4: 0.0, 5: 0.0}) == 0.0  # 0*ln0 := 0


def test_entropy_uniform_is_ln_support_size():
    for m in (2, 3, 5, 8):
        pd = {k: 1.0 / m for k in range(m)}
        assert prob_dist_entropy(pd) == approx_ln(m)


def test_entropy_matches_closed_form_on_hand_checked_dist():
    pd = {0: 0.5, 1: 0.25, 2: 0.25}
    expected = -(0.5 * math.log(0.5) + 0.25 * math.log(0.25) + 0.25 * math.log(0.25))
    assert prob_dist_entropy(pd) == _approx(expected)


def test_entropy_label_invariant():
    """Same probability profile on a SHIFTED integer support -> identical entropy."""
    a = {0: 0.6, 1: 0.3, 2: 0.1}
    b = {40: 0.6, 41: 0.3, 42: 0.1}  # center/support moved, profile unchanged
    assert prob_dist_entropy(a) == _approx(prob_dist_entropy(b))


def test_entropy_sigma_hat_is_row_aligned():
    dists = [{0: 1.0}, {0: 0.5, 1: 0.5}, {0: 1.0 / 3, 1: 1.0 / 3, 2: 1.0 / 3}]
    sig = entropy_sigma_hat(dists)
    assert sig.shape == (3,)
    assert sig[0] == 0.0
    assert sig[1] == _approx(math.log(2))
    assert sig[2] == _approx(math.log(3))


# --- Spearman helper (tie-corrected; no scipy) --------------------------------


def test_spearman_perfect_monotone():
    assert spearman_rho([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == _approx(1.0)


def test_spearman_perfect_anti_monotone():
    assert spearman_rho([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == _approx(-1.0)


def test_spearman_tie_corrected_known_value():
    # x ranks [1, 2.5, 2.5, 4] vs y ranks [1, 2, 3, 4] -> rho = 4.5/sqrt(4.5*5.0).
    rho = spearman_rho([1, 2, 2, 3], [10, 20, 30, 40])
    assert rho == _approx(4.5 / math.sqrt(4.5 * 5.0))


def test_spearman_constant_side_is_nan():
    assert math.isnan(spearman_rho([1, 1, 1, 1], [1, 2, 3, 4]))


# --- sanity check 1: monotonicity vs |integer error| --------------------------


def test_monotonicity_sanity_passes_on_monotone_axis():
    sigma = [0.1, 0.2, 0.3, 0.4, 0.5]
    abs_err = [0, 1, 2, 3, 4]
    res = monotonicity_sanity(sigma, abs_err, min_rho=0.10)
    assert res["passed"] is True
    assert res["rho"] == _approx(1.0)


def test_monotonicity_sanity_fails_below_threshold():
    # Deterministic weak-but-positive association: rho ~ 0.058 (> 0 yet < 0.10), so the
    # sign passes but the magnitude fails -> the binding threshold is what rejects it.
    sigma = list(range(10))
    abs_err = [0, 0, 0, 0, 0, 1, 0, 0, 0, 0]
    res = monotonicity_sanity(sigma, abs_err, min_rho=0.10)
    assert 0.0 < res["rho"] < 0.10
    assert res["passed"] is False


def test_monotonicity_sanity_fails_on_negative_rho():
    res = monotonicity_sanity([1, 2, 3, 4], [4, 3, 2, 1], min_rho=0.10)
    assert res["passed"] is False
    assert res["rho"] == _approx(-1.0)


def test_monotonicity_sanity_fails_on_constant_axis():
    res = monotonicity_sanity([0.3, 0.3, 0.3, 0.3], [0, 1, 2, 3], min_rho=0.10)
    assert res["passed"] is False  # nan rho


# --- sanity check 2: no per-CP collapse ---------------------------------------


def test_per_cp_distinct_passes_when_all_cps_diverse():
    sigma = [0.1, 0.2, 0.3, 1.1, 1.2, 1.3, 2.1, 2.2, 2.3]
    cp = ["22:00", "22:00", "22:00", "23:00", "23:00", "23:00", "18:00", "18:00", "18:00"]
    res = per_cp_distinct_sanity(sigma, cp, focus_cps=["22:00", "23:00"], min_distinct=3)
    assert res["passed"] is True
    assert res["by_cp_distinct"] == {"22:00": 3, "23:00": 3, "18:00": 3}


def test_per_cp_distinct_detects_collapsed_focus_cp():
    # 23:00 collapses to a single value -> the late-CP regime cannot be differentiated.
    sigma = [0.1, 0.2, 0.3, 0.9, 0.9, 0.9]
    cp = ["22:00", "22:00", "22:00", "23:00", "23:00", "23:00"]
    res = per_cp_distinct_sanity(sigma, cp, focus_cps=["22:00", "23:00"], min_distinct=3)
    assert res["passed"] is False
    assert res["by_cp_distinct"]["23:00"] == 1


def test_per_cp_distinct_fails_when_focus_cp_absent():
    sigma = [0.1, 0.2, 0.3]
    cp = ["18:00", "18:00", "18:00"]
    res = per_cp_distinct_sanity(sigma, cp, focus_cps=["22:00", "23:00"], min_distinct=3)
    assert res["passed"] is False
    assert res["focus_present"] == {"22:00": False, "23:00": False}


# --- conformal path: calib-frozen P1 floor (no-leak, determinism, flooring) ---


def _trackP_config() -> NormalizedConformalConfig:
    return NormalizedConformalConfig(
        sigma_is_variance=False, method_version="1.3", sigma_floor_percentile=1.0
    )


def _calib_fixture():
    rng = np.random.default_rng(7)
    n = 400
    yp = rng.normal(15.0, 3.0, n)
    sigma = np.abs(rng.normal(1.0, 0.4, n)) + 0.05  # entropy-like positive proxy
    yt = np.round(yp + rng.normal(0.0, sigma)).astype(int)
    return yt, yp, sigma


def test_floor_is_calib_p1_and_frozen_on_apply():
    yt, yp, sigma = _calib_fixture()
    cal = fit_normalized_conformal(yt, yp, list(sigma), config=_trackP_config())
    expected_floor = float(np.percentile(sigma, 1.0))
    assert cal.sigma_floor == _approx(expected_floor)

    # Apply on a test set whose sigma is MUCH smaller (different distribution): the
    # frozen calib floor must be reused, NOT re-estimated from the test sigma.
    test_pred = np.array([15.0, 16.0, 17.0, 18.0])
    tiny = [1e-9, 1e-9, 1e-9, 1e-9]
    lo, hi = apply_normalized_conformal(cal, test_pred, tiny)
    sig_reproduced, _, _ = _prepare_sigma(
        tiny, is_variance=False, median=cal.sigma_median, floor=cal.sigma_floor
    )
    assert np.all(sig_reproduced == cal.sigma_floor)  # all floored to the frozen P1
    exp_lo, exp_hi = _normalized_int_interval(test_pred, sig_reproduced, cal.q_lo, cal.q_hi)
    assert np.array_equal(lo, exp_lo)
    assert np.array_equal(hi, exp_hi)


def test_sigma_hat_at_least_floor_after_preparation():
    yt, yp, sigma = _calib_fixture()
    cal = fit_normalized_conformal(yt, yp, list(sigma), config=_trackP_config())
    prepared, _, _ = _prepare_sigma(
        list(sigma), is_variance=False, median=cal.sigma_median, floor=cal.sigma_floor
    )
    assert float(prepared.min()) >= cal.sigma_floor


def test_trackP_fit_is_deterministic():
    yt, yp, sigma = _calib_fixture()
    a = fit_normalized_conformal(yt, yp, list(sigma), config=_trackP_config())
    b = fit_normalized_conformal(yt, yp, list(sigma), config=_trackP_config())
    assert (a.c, a.q_lo, a.q_hi, a.sigma_floor, a.sigma_median) == (
        b.c,
        b.q_lo,
        b.q_hi,
        b.sigma_floor,
        b.sigma_median,
    )
    test_pred = np.linspace(10.0, 20.0, 25)
    test_sigma = list(np.linspace(0.2, 2.0, 25))
    lo_a, hi_a = apply_normalized_conformal(a, test_pred, test_sigma)
    lo_b, hi_b = apply_normalized_conformal(b, test_pred, test_sigma)
    assert np.array_equal(lo_a, lo_b) and np.array_equal(hi_a, hi_b)


def test_sanity_helpers_are_deterministic_on_rerun():
    yt, yp, sigma = _calib_fixture()
    abs_err = np.abs(yt - np.round(yp).astype(int)).astype(float)
    r1 = monotonicity_sanity(sigma, abs_err, min_rho=0.10)
    r2 = monotonicity_sanity(sigma, abs_err, min_rho=0.10)
    assert r1 == r2


# --- reduction sanity: constant sigma_hat -> collapsed-proxy path detected ----


def test_constant_sigma_reduces_to_fixed_offsets_and_is_detected():
    rng = np.random.default_rng(3)
    n = 200
    yp = rng.normal(15.0, 3.0, n)
    yt = np.round(yp + rng.normal(0.0, 1.0, n)).astype(int)
    const_sigma = [0.7] * n  # degenerate proxy: identical for every row
    cal = fit_normalized_conformal(yt, yp, const_sigma, config=_trackP_config())

    # Two rows with the SAME point forecast and constant sigma get an identical interval:
    # the continuous offsets q_lo*sigma / q_hi*sigma are constant (fixed-width global).
    same_pred = np.array([15.25, 15.25])
    lo, hi = apply_normalized_conformal(cal, same_pred, [0.7, 0.7])
    assert lo[0] == lo[1] and hi[0] == hi[1]

    # The collapsed-proxy is reachable + DETECTED by the per-CP sanity check.
    cp = ["22:00"] * (n // 2) + ["23:00"] * (n - n // 2)
    res = per_cp_distinct_sanity(const_sigma, cp, focus_cps=["22:00", "23:00"], min_distinct=3)
    assert res["passed"] is False
    assert all(v == 1 for v in res["by_cp_distinct"].values())


# --- small numeric helpers ----------------------------------------------------


def _approx(x: float, tol: float = 1e-12) -> "_Approx":
    return _Approx(x, tol)


def approx_ln(m: int) -> "_Approx":
    return _Approx(math.log(m), 1e-12)


class _Approx:
    def __init__(self, x: float, tol: float):
        self.x = float(x)
        self.tol = float(tol)

    def __eq__(self, other) -> bool:
        return abs(float(other) - self.x) <= self.tol

    def __repr__(self) -> str:
        return f"~{self.x}+-{self.tol}"
