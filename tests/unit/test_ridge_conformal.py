"""ridge_conformal_minimal: per-CP abs-residual quantile + hierarchical fallback."""

from __future__ import annotations

from core.models.ridge_conformal import fit_cp_abs_conformal, interval


def test_cp_specific_quantile_and_symmetric_interval():
    # CP 23: abs-residuals mostly 1, a few 3 -> 80% quantile = small half-width.
    cps = ["23:00"] * 40
    resid = [1] * 34 + [3] * 6
    cal = fit_cp_abs_conformal(resid, cps, coverage=0.80, n_min=30)
    lo, hi, src = interval(cal, p50_int=18, cp="23:00")
    assert src == "cp_specific"
    assert hi - lo == 2 * cal.q_by_cp["23:00"] and lo == 18 - cal.q_by_cp["23:00"]
    assert cal.q_by_cp["23:00"] >= 1  # covers >=80%


def test_fallback_to_global_pool_when_cp_thin():
    cps = ["23:00"] * 40 + ["20:00"] * 5  # 20:00 below n_min=30
    resid = [1] * 40 + [2] * 5
    cal = fit_cp_abs_conformal(resid, cps, coverage=0.80, n_min=30)
    _, _, src = interval(cal, p50_int=15, cp="20:00")
    assert src == "global_cp_pool"
    _, _, src23 = interval(cal, p50_int=15, cp="23:00")
    assert src23 == "cp_specific"


def test_insufficient_data_degenerate_point():
    cal = fit_cp_abs_conformal([], [], coverage=0.80, n_min=30)
    lo, hi, src = interval(cal, p50_int=12, cp="23:00")
    assert (lo, hi, src) == (12, 12, "insufficient_data")


def test_quantile_covers_at_least_coverage():
    # empirical check: half-width q must contain >= 80% of abs-residuals.
    import numpy as np
    rng = np.random.default_rng(0)
    resid = np.abs(rng.integers(0, 5, 200)).tolist()
    cal = fit_cp_abs_conformal(resid, ["23:00"] * 200, coverage=0.80, n_min=30)
    q = cal.q_by_cp["23:00"]
    assert (np.asarray(resid) <= q).mean() >= 0.80
