"""Track P' (quantization-margin sigma) - method + sanity unit tests.

Pre-registered in ``contracts/phase5_amendment_trackPprime_quantization_margin.md``
(conformal_method_version 1.4). Covers: the margin closed-form incl. the ``frac=0.5 -> 0.5`` /
``frac=0.0 -> 0.0`` corners and label-invariance; the calib-frozen P1 floor no-leak /
determinism wired into the v1.0 conformal path; the auxiliary tie-corrected Kendall ``tau-b``;
the BINDING focus-subset auditor (pass/fail/empty + the read-only n_subset/ties/tau-b fields);
and the reduction-to-fixed-width / collapsed-proxy path.
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
from core.eval.sanity_trackPprime import (
    focus_subset_audit,
    kendall_tau_b,
    margin_sigma_hat,
    monotonicity_sanity,
    per_cp_distinct_sanity,
)


# --- margin proxy closed-form (sigma_hat = 0.5 - |frac - 0.5|; corners; invariance) ---


def test_margin_corners_integer_and_half():
    sig = margin_sigma_hat([3.0, 3.5, 4.0, 10.5])
    assert sig[0] == _approx(0.0)   # frac 0.0 -> on integer -> easiest
    assert sig[1] == _approx(0.5)   # frac 0.5 -> on rounding edge -> hardest
    assert sig[2] == _approx(0.0)
    assert sig[3] == _approx(0.5)


def test_margin_hand_checked_fractions():
    # frac 0.25 -> |0.25-0.5|=0.25 -> sigma_hat 0.25 ; frac 0.9 -> |0.4|=0.4 -> 0.10
    sig = margin_sigma_hat([7.25, 7.9, 7.1])
    assert sig[0] == _approx(0.25)
    assert sig[1] == _approx(0.10)
    assert sig[2] == _approx(0.10)


def test_margin_range_is_zero_to_half():
    rng = np.random.default_rng(0)
    sig = margin_sigma_hat(rng.uniform(-50.0, 50.0, 500))
    assert float(sig.min()) >= 0.0
    assert float(sig.max()) <= 0.5 + 1e-12


def test_margin_label_invariant_under_integer_shift():
    base = [0.2, 0.5, 0.8, 0.35]
    shifted = [x + 41.0 for x in base]  # integer shift -> identical fractional parts
    assert np.allclose(margin_sigma_hat(base), margin_sigma_hat(shifted))


def test_margin_is_row_aligned():
    sig = margin_sigma_hat([1.0, 2.5, 3.25])
    assert sig.shape == (3,)
    assert sig[0] == _approx(0.0) and sig[1] == _approx(0.5) and sig[2] == _approx(0.25)


# --- auxiliary Kendall tau-b (tie-corrected; read-only; no scipy) --------------


def test_kendall_perfect_monotone_is_one():
    assert kendall_tau_b([1, 2, 3, 4], [10, 20, 30, 40]) == _approx(1.0)


def test_kendall_perfect_anti_is_minus_one():
    assert kendall_tau_b([1, 2, 3, 4], [40, 30, 20, 10]) == _approx(-1.0)


def test_kendall_tie_corrected_known_value():
    # x=[1,1,2,3], y=[1,2,3,4]: concordant-disc=5; n0=6; n1=1 (one x-tie pair); n2=0.
    # tau_b = 5 / sqrt((6-1)*(6-0)) = 5/sqrt(30).
    assert kendall_tau_b([1, 1, 2, 3], [1, 2, 3, 4]) == _approx(5.0 / math.sqrt(30.0))


def test_kendall_constant_side_is_nan():
    assert math.isnan(kendall_tau_b([1, 1, 1, 1], [1, 2, 3, 4]))


# --- focus-subset auditor (BINDING focus Spearman + read-only audit fields) ----


def test_focus_audit_passes_and_reports_audit_fields():
    sigma = [0.1, 0.2, 0.3, 0.4, 0.5, 0.05]
    abs_err = [0, 1, 2, 3, 4, 0]
    cp = ["22:00", "22:00", "23:00", "23:00", "22:00", "18:00"]
    res = focus_subset_audit(sigma, abs_err, cp, focus_cps=["22:00", "23:00"], min_rho=0.10)
    assert res["passed"] is True
    assert res["n_subset"] == 5            # the 18:00 row is excluded
    assert res["abs_error_distinct"] == 5  # {0,1,2,3,4} on the focus subset
    assert res["kendall_tau_b_is_binding"] is False
    assert math.isfinite(res["kendall_tau_b"])


def test_focus_audit_fails_when_focus_not_monotone():
    sigma = [0.5, 0.4, 0.3, 0.2, 0.1]   # anti-correlated with error -> rho<0
    abs_err = [0, 1, 2, 3, 4]
    cp = ["22:00", "22:00", "23:00", "23:00", "23:00"]
    res = focus_subset_audit(sigma, abs_err, cp, focus_cps=["22:00", "23:00"], min_rho=0.10)
    assert res["passed"] is False
    assert res["rho"] < 0.0


def test_focus_audit_empty_subset_fails():
    sigma = [0.1, 0.2, 0.3]
    abs_err = [0, 1, 2]
    cp = ["18:00", "18:00", "18:00"]   # no focus CP present
    res = focus_subset_audit(sigma, abs_err, cp, focus_cps=["22:00", "23:00"], min_rho=0.10)
    assert res["passed"] is False
    assert res["n_subset"] == 0
    assert math.isnan(res["kendall_tau_b"])


def test_focus_audit_tau_b_is_never_binding_even_if_high():
    # Spearman below floor (weak) but tau_b finite: pass/fail follows Spearman, not tau_b.
    sigma = list(range(10))
    abs_err = [0, 0, 0, 0, 0, 1, 0, 0, 0, 0]   # rho ~ 0.058 < 0.10
    cp = ["22:00"] * 10
    res = focus_subset_audit(sigma, abs_err, cp, focus_cps=["22:00", "23:00"], min_rho=0.10)
    assert 0.0 < res["rho"] < 0.10
    assert res["passed"] is False


# --- reused binding sanity helpers still behave on margin-shaped inputs --------


def test_global_monotonicity_passes_on_margin_axis():
    sigma = [0.05, 0.1, 0.2, 0.3, 0.45]
    abs_err = [0, 1, 2, 3, 4]
    res = monotonicity_sanity(sigma, abs_err, min_rho=0.10)
    assert res["passed"] is True
    assert res["rho"] == _approx(1.0)


def test_per_cp_distinct_detects_collapsed_focus_cp():
    sigma = [0.1, 0.2, 0.3, 0.25, 0.25, 0.25]
    cp = ["22:00", "22:00", "22:00", "23:00", "23:00", "23:00"]
    res = per_cp_distinct_sanity(sigma, cp, focus_cps=["22:00", "23:00"], min_distinct=3)
    assert res["passed"] is False
    assert res["by_cp_distinct"]["23:00"] == 1


# --- conformal path: calib-frozen P1 floor (no-leak, determinism, flooring) ----


def _trackPprime_config() -> NormalizedConformalConfig:
    return NormalizedConformalConfig(
        sigma_is_variance=False, method_version="1.4", sigma_floor_percentile=1.0
    )


def _calib_fixture():
    rng = np.random.default_rng(11)
    n = 400
    yp = rng.uniform(10.0, 20.0, n)            # decimals exercise the rounding edge
    sigma = margin_sigma_hat(yp)
    yt = np.round(yp + rng.normal(0.0, 0.5 + sigma)).astype(int)
    return yt, yp, sigma


def test_floor_is_calib_p1_and_frozen_on_apply():
    yt, yp, sigma = _calib_fixture()
    cal = fit_normalized_conformal(yt, yp, list(sigma), config=_trackPprime_config())
    assert cal.sigma_floor == _approx(float(np.percentile(sigma, 1.0)))

    test_pred = np.array([15.0, 16.0, 17.0, 18.0])
    tiny = [1e-9, 1e-9, 1e-9, 1e-9]            # all below the frozen calib floor
    lo, hi = apply_normalized_conformal(cal, test_pred, tiny)
    sig_reproduced, _, _ = _prepare_sigma(
        tiny, is_variance=False, median=cal.sigma_median, floor=cal.sigma_floor
    )
    assert np.all(sig_reproduced == cal.sigma_floor)
    exp_lo, exp_hi = _normalized_int_interval(test_pred, sig_reproduced, cal.q_lo, cal.q_hi)
    assert np.array_equal(lo, exp_lo) and np.array_equal(hi, exp_hi)


def test_sigma_hat_at_least_floor_after_preparation():
    yt, yp, sigma = _calib_fixture()
    cal = fit_normalized_conformal(yt, yp, list(sigma), config=_trackPprime_config())
    prepared, _, _ = _prepare_sigma(
        list(sigma), is_variance=False, median=cal.sigma_median, floor=cal.sigma_floor
    )
    assert float(prepared.min()) >= cal.sigma_floor


def test_trackPprime_fit_is_deterministic():
    yt, yp, sigma = _calib_fixture()
    a = fit_normalized_conformal(yt, yp, list(sigma), config=_trackPprime_config())
    b = fit_normalized_conformal(yt, yp, list(sigma), config=_trackPprime_config())
    assert (a.c, a.q_lo, a.q_hi, a.sigma_floor, a.sigma_median) == (
        b.c, b.q_lo, b.q_hi, b.sigma_floor, b.sigma_median,
    )


def test_audit_is_deterministic_on_rerun():
    yt, yp, sigma = _calib_fixture()
    abs_err = np.abs(yt - np.round(yp).astype(int)).astype(float)
    cp = ["22:00" if i % 2 else "23:00" for i in range(len(sigma))]
    r1 = focus_subset_audit(sigma, abs_err, cp, focus_cps=["22:00", "23:00"], min_rho=0.10)
    r2 = focus_subset_audit(sigma, abs_err, cp, focus_cps=["22:00", "23:00"], min_rho=0.10)
    assert r1 == r2


# --- reduction sanity: constant sigma_hat -> collapsed-proxy path detected ------


def test_constant_sigma_reduces_to_fixed_offsets_and_is_detected():
    rng = np.random.default_rng(5)
    n = 200
    yp = rng.normal(15.0, 3.0, n)
    yt = np.round(yp + rng.normal(0.0, 1.0, n)).astype(int)
    const_sigma = [0.3] * n
    cal = fit_normalized_conformal(yt, yp, const_sigma, config=_trackPprime_config())
    same_pred = np.array([15.25, 15.25])
    lo, hi = apply_normalized_conformal(cal, same_pred, [0.3, 0.3])
    assert lo[0] == lo[1] and hi[0] == hi[1]

    cp = ["22:00"] * (n // 2) + ["23:00"] * (n - n // 2)
    res = per_cp_distinct_sanity(const_sigma, cp, focus_cps=["22:00", "23:00"], min_distinct=3)
    assert res["passed"] is False
    assert all(v == 1 for v in res["by_cp_distinct"].values())


# --- small numeric helper ------------------------------------------------------


def _approx(x: float, tol: float = 1e-12) -> "_Approx":
    return _Approx(x, tol)


class _Approx:
    def __init__(self, x: float, tol: float):
        self.x = float(x)
        self.tol = float(tol)

    def __eq__(self, other) -> bool:
        return abs(float(other) - self.x) <= self.tol

    def __repr__(self) -> str:
        return f"~{self.x}+-{self.tol}"
