"""Split-conformal calibration tests (design 8.2 / REQ-MOD-4).

The load-bearing property is MARGINAL COVERAGE: a calibrator fit on one residual
sample must cover ~``1 - alpha`` of a FRESH test sample. We verify this on
synthetic data with a known noise law, plus the structural promises of the module:
- ``signed`` corrects a biased point forecast (asymmetric offsets) and stays sharper
  than ``absolute`` when residuals are skewed;
- per-CP offsets widen for a noisier CP;
- bucket -> cp -> pooled fallback resolves in that order (n_min gates each level);
- ``apply_conformal`` emits ordered integer brackets;
- the fit is deterministic (sorting only, no RNG -> REQ-MOD-6 safe) and validates
  its inputs.

Coverage bands are theory-grounded (n large; binomial SE ~0.005) and the seed is
fixed, so the assertions are deterministic, not flaky.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.calibration.conformal import (
    ConformalConfig,
    CoverageReport,
    MondrianConformalConfig,
    NormalizedConformalConfig,
    _assign_buckets,
    _merge_edges_until_min_n,
    _mondrian_edges,
    _normalized_int_interval,
    _offsets_from_residuals,
    _prepare_sigma,
    _winsorize_sigma,
    apply_conformal,
    apply_mondrian_conformal,
    apply_normalized_conformal,
    coverage_report,
    fit_conformal,
    fit_mondrian_conformal,
    fit_normalized_conformal,
    interval_dec,
    _offsets_for_row,
)


def _block(
    rng: np.random.Generator,
    n: int,
    *,
    cp: str,
    mean: float = 0.0,
    std: float = 1.0,
    month: int | None = None,
    y_pred_loc: float = 15.0,
):
    """One homogeneous block: ``residual = y_true - y_pred ~ N(mean, std)``.

    ``y_pred`` itself is arbitrary (a plausible temperature) -- coverage depends only
    on the residual law, so the data-generating ``y_pred`` must not matter.
    """
    y_pred = rng.normal(y_pred_loc, 3.0, n)
    resid = rng.normal(mean, std, n)
    y_true = y_pred + resid
    cps = [cp] * n
    months = [month] * n if month is not None else None
    return y_true, y_pred, cps, months


def _coverage(lo: np.ndarray, hi: np.ndarray, y: np.ndarray) -> float:
    return float(((lo <= y) & (y <= hi)).mean())


# --- marginal coverage on a fresh split --------------------------------------

def test_absolute_marginal_coverage_on_holdout():
    """Symmetric noise: split-conformal ``absolute`` covers ~0.80 (>= by guarantee)."""
    rng = np.random.default_rng(42)
    yt_c, yp_c, cp_c, _ = _block(rng, 8000, cp="23", mean=0.0, std=2.0)
    yt_t, yp_t, cp_t, _ = _block(rng, 8000, cp="23", mean=0.0, std=2.0)
    cal = fit_conformal(yt_c, yp_c, cp_c, config=ConformalConfig(method="absolute"))
    lo, hi = interval_dec(cal, yp_t, cp_t)
    cov = _coverage(lo, hi, yt_t)
    assert 0.78 <= cov <= 0.84  # finite-sample: at-or-slightly-above 0.80


def test_signed_marginal_coverage_on_holdout():
    """Symmetric noise: ``signed`` two-sided quantiles also land at ~0.80."""
    rng = np.random.default_rng(7)
    yt_c, yp_c, cp_c, _ = _block(rng, 8000, cp="23", mean=0.0, std=2.0)
    yt_t, yp_t, cp_t, _ = _block(rng, 8000, cp="23", mean=0.0, std=2.0)
    cal = fit_conformal(yt_c, yp_c, cp_c, config=ConformalConfig(method="signed"))
    lo, hi = interval_dec(cal, yp_t, cp_t)
    cov = _coverage(lo, hi, yt_t)
    assert 0.775 <= cov <= 0.825


# --- signed corrects a biased point forecast ---------------------------------

def test_signed_corrects_bias_and_is_sharper_than_absolute():
    """A +2C biased point forecast: signed shifts BOTH offsets up, keeps coverage,
    and yields a NARROWER interval than absolute (which over-covers under skew)."""
    rng = np.random.default_rng(123)
    yt_c, yp_c, cp_c, _ = _block(rng, 8000, cp="23", mean=2.0, std=1.0)
    yt_t, yp_t, cp_t, _ = _block(rng, 8000, cp="23", mean=2.0, std=1.0)

    cal_s = fit_conformal(yt_c, yp_c, cp_c, config=ConformalConfig(method="signed"))
    cal_a = fit_conformal(yt_c, yp_c, cp_c, config=ConformalConfig(method="absolute"))

    # both offsets shifted positive to track the biased truth
    assert cal_s.pooled.lo_offset > 0.0
    assert cal_s.pooled.hi_offset > cal_s.pooled.lo_offset

    lo_s, hi_s = interval_dec(cal_s, yp_t, cp_t)
    lo_a, hi_a = interval_dec(cal_a, yp_t, cp_t)
    assert 0.77 <= _coverage(lo_s, hi_s, yt_t) <= 0.83  # signed still ~0.80
    assert _coverage(lo_a, hi_a, yt_t) >= 0.78  # absolute still covers (over-covers under skew)

    # signed is sharper when residuals are biased/skewed
    assert float((hi_s - lo_s).mean()) < float((hi_a - lo_a).mean())


# --- per-CP heteroscedasticity ------------------------------------------------

def test_per_cp_offsets_widen_for_noisier_cp():
    """A noisy CP must get a wider per-CP interval than a calm CP."""
    rng = np.random.default_rng(11)
    yt0, yp0, cp0, _ = _block(rng, 2000, cp="20", mean=0.0, std=0.5)  # calm
    yt3, yp3, cp3, _ = _block(rng, 2000, cp="23", mean=0.0, std=3.0)  # noisy
    yt = np.concatenate([yt0, yt3])
    yp = np.concatenate([yp0, yp3])
    cp = cp0 + cp3
    cal = fit_conformal(yt, yp, cp, config=ConformalConfig(method="signed"))
    assert "20" in cal.by_cp and "23" in cal.by_cp
    w20 = cal.by_cp["20"].hi_offset - cal.by_cp["20"].lo_offset
    w23 = cal.by_cp["23"].hi_offset - cal.by_cp["23"].lo_offset
    assert w23 > w20


# --- fallback chain: bucket -> cp -> pooled -----------------------------------

def test_bucket_kept_above_n_min_else_falls_back_to_cp():
    """The big bucket is kept and used; the small one is dropped and falls back to CP."""
    rng = np.random.default_rng(5)
    # cp "23", month 7: 300 rows (>= n_min_bucket=200) -> bucket kept
    yt7, yp7, cp7, mo7 = _block(rng, 300, cp="23", mean=0.0, std=3.0, month=7)
    # cp "23", month 1: 100 rows (< 200) -> bucket dropped, falls back to per-CP "23"
    yt1, yp1, cp1, mo1 = _block(rng, 100, cp="23", mean=0.0, std=0.5, month=1)
    yt = np.concatenate([yt7, yt1])
    yp = np.concatenate([yp7, yp1])
    cp = cp7 + cp1
    month = mo7 + mo1
    cal = fit_conformal(
        yt, yp, cp, config=ConformalConfig(method="signed", n_min_bucket=200, min_calib=30),
        month=month,
    )
    assert (7, None, "23") in cal.by_bucket  # large bucket survived
    assert (1, None, "23") not in cal.by_bucket  # small bucket dropped

    off_big = _offsets_for_row(cal, "23", 7, None)
    off_small = _offsets_for_row(cal, "23", 1, None)
    assert off_big is cal.by_bucket[(7, None, "23")]  # bucket used
    assert off_small is cal.by_cp["23"]  # fell back to per-CP


def test_unknown_cp_falls_back_to_pooled():
    """A CP never seen in calibration resolves to the pooled calibrator."""
    rng = np.random.default_rng(99)
    yt, yp, cp, _ = _block(rng, 1000, cp="23", mean=0.0, std=2.0)
    cal = fit_conformal(yt, yp, cp, config=ConformalConfig(method="signed"))
    off = _offsets_for_row(cal, "21", None, None)  # "21" unseen
    assert off is cal.pooled


# --- integer emission ---------------------------------------------------------

def test_apply_conformal_emits_ordered_integer_brackets():
    """Quantized bounds are int32, hi >= lo everywhere, and still cover ~>= target."""
    rng = np.random.default_rng(3)
    yt_c, yp_c, cp_c, _ = _block(rng, 6000, cp="23", mean=0.0, std=2.0)
    yt_t, yp_t, cp_t, _ = _block(rng, 6000, cp="23", mean=0.0, std=2.0)
    cal = fit_conformal(yt_c, yp_c, cp_c, config=ConformalConfig(method="signed"))
    lo_i, hi_i = apply_conformal(cal, yp_t, cp_t)
    assert lo_i.dtype == np.int32 and hi_i.dtype == np.int32
    assert np.all(hi_i >= lo_i)
    yt_int = np.array([round(v) for v in yt_t], dtype=int)
    cov_int = _coverage(lo_i, hi_i, yt_int)
    assert cov_int >= 0.76  # rounding the bounds out never destroys coverage


# --- coverage_report semantics ------------------------------------------------

def test_coverage_report_fields_on_handbuilt_case():
    lo = [10, 10, 10, 10]
    hi = [12, 12, 12, 12]
    yt = [11, 11, 13, 9]  # covered: T, T, F, F -> 0.5
    rep = coverage_report(lo, hi, yt, ["23", "23", "23", "23"], target=0.80, tol=0.04)
    assert isinstance(rep, CoverageReport)
    assert rep.coverage == pytest.approx(0.5)
    assert rep.mean_width_brackets == pytest.approx(3.0)  # hi - lo + 1
    assert rep.abs_error == pytest.approx(0.30)
    assert rep.within_tol is False
    assert rep.n == 4
    cov_cp, w_cp, n_cp = rep.by_cp["23"]
    assert cov_cp == pytest.approx(0.5)
    assert w_cp == pytest.approx(3.0)
    assert n_cp == 4


def test_coverage_report_within_tol_when_on_target():
    """80/100 covered -> coverage 0.80 -> within the 0.04 tolerance."""
    lo = [0] * 100
    hi = [1] * 100  # bracket [0,1]
    yt = [0] * 80 + [5] * 20  # first 80 covered, last 20 outside
    rep = coverage_report(lo, hi, yt, ["23"] * 100)
    assert rep.coverage == pytest.approx(0.80)
    assert rep.within_tol is True


# --- finite-sample rank clamping / certified flag -----------------------------

def test_certified_false_when_n_too_small_to_certify():
    """n=3 cannot certify 0.80 coverage -> rank clamps to the extreme, certified=False."""
    off_abs = _offsets_from_residuals(np.array([0.0, 1.0, 2.0]), coverage=0.80, method="absolute")
    assert off_abs.certified is False
    assert off_abs.n_calib == 3
    off_sig = _offsets_from_residuals(np.array([-1.0, 0.0, 1.0]), coverage=0.80, method="signed")
    assert off_sig.certified is False


def test_certified_true_with_ample_calibration():
    rng = np.random.default_rng(1)
    off = _offsets_from_residuals(rng.normal(0, 1, 500), coverage=0.80, method="absolute")
    assert off.certified is True
    assert off.n_calib == 500


# --- input validation ---------------------------------------------------------

def test_fit_rejects_bad_method_and_coverage():
    yt, yp, cp = [1.0, 2.0], [1.0, 2.0], ["23", "23"]
    with pytest.raises(ValueError):
        fit_conformal(yt, yp, cp, config=ConformalConfig(method="quantile"))
    with pytest.raises(ValueError):
        fit_conformal(yt, yp, cp, config=ConformalConfig(coverage=1.5))


def test_fit_rejects_length_mismatch_and_empty():
    with pytest.raises(ValueError):
        fit_conformal([1.0, 2.0], [1.0], ["23", "23"])
    with pytest.raises(ValueError):
        fit_conformal([], [], [])


def test_offsets_reject_nan_and_empty_residuals():
    with pytest.raises(ValueError):
        _offsets_from_residuals(np.array([]), coverage=0.80, method="signed")
    with pytest.raises(ValueError):
        _offsets_from_residuals(np.array([0.0, np.nan, 1.0]), coverage=0.80, method="signed")


# --- determinism (REQ-MOD-6) --------------------------------------------------

def test_fit_is_deterministic():
    """Same inputs -> byte-identical offsets (sorting only, no RNG)."""
    rng = np.random.default_rng(2024)
    yt, yp, cp, mo = _block(rng, 1000, cp="23", mean=0.5, std=2.0, month=6)
    c1 = fit_conformal(yt, yp, cp, config=ConformalConfig(method="signed"), month=mo)
    c2 = fit_conformal(yt, yp, cp, config=ConformalConfig(method="signed"), month=mo)
    assert c1.pooled == c2.pooled
    assert c1.by_cp.keys() == c2.by_cp.keys()
    for k in c1.by_cp:
        assert c1.by_cp[k] == c2.by_cp[k]
    assert c1.by_bucket.keys() == c2.by_bucket.keys()


# --- normalized quantization-aware conformal (Phase 5 amendment) --------------
# The load-bearing property here is that the calibrator is fit on the SAME
# integer-inclusive bracket object the gate evaluates: in-sample integer coverage
# lands in the pre-registered band on calib, and a fresh sample with the same law
# is covered near target. Determinism is sorting/quantile only (no RNG).


def _maxtraj_block(
    rng: np.random.Generator, n: int, *, sigma_lo: float, sigma_hi: float
):
    """Heteroscedastic block: per-row variance proxy ``p50_var`` in [sigma_lo, sigma_hi]^2,
    truth = Q(y_pred + N(0, sqrt(p50_var))). Returns (y_true_int, y_pred_dec, p50_var)."""
    yp = rng.normal(15.0, 3.0, n)
    std = rng.uniform(sigma_lo, sigma_hi, n)
    p50_var = (std ** 2).tolist()
    yt = np.floor(yp + rng.normal(0.0, 1.0, n) * std + 0.5).astype(int)
    return yt, yp, p50_var


def test_normalized_calib_coverage_lands_in_band():
    """c is selected on calib so in-sample integer coverage sits in [band_lo, band_hi]."""
    rng = np.random.default_rng(42)
    yt, yp, pv = _maxtraj_block(rng, 4000, sigma_lo=0.5, sigma_hi=2.5)
    cal = fit_normalized_conformal(yt, yp, pv, config=NormalizedConformalConfig())
    assert cal.in_band is True
    assert cal.config.band_lo <= cal.calib_coverage <= cal.config.band_hi


def test_normalized_marginal_coverage_on_holdout():
    """A fresh sample from the SAME law is covered near the 0.80 target."""
    rng = np.random.default_rng(7)
    yt_c, yp_c, pv_c = _maxtraj_block(rng, 6000, sigma_lo=0.5, sigma_hi=2.5)
    yt_t, yp_t, pv_t = _maxtraj_block(rng, 6000, sigma_lo=0.5, sigma_hi=2.5)
    cal = fit_normalized_conformal(yt_c, yp_c, pv_c)
    lo, hi = apply_normalized_conformal(cal, yp_t, pv_t)
    cov = _coverage(lo, hi, yt_t)
    assert 0.76 <= cov <= 0.84


def test_normalized_emits_ordered_integer_brackets():
    rng = np.random.default_rng(3)
    yt, yp, pv = _maxtraj_block(rng, 2000, sigma_lo=0.5, sigma_hi=2.5)
    cal = fit_normalized_conformal(yt, yp, pv)
    lo, hi = apply_normalized_conformal(cal, yp, pv)
    assert lo.dtype == np.int32 and hi.dtype == np.int32
    assert np.all(hi >= lo)


def test_normalized_widths_are_non_degenerate_under_heteroscedastic_sigma():
    """A spread of p50_var must yield multiple distinct integer widths (het evidence)."""
    rng = np.random.default_rng(11)
    yt, yp, pv = _maxtraj_block(rng, 3000, sigma_lo=0.3, sigma_hi=3.0)
    cal = fit_normalized_conformal(yt, yp, pv)
    lo, hi = apply_normalized_conformal(cal, yp, pv)
    widths = (hi - lo + 1)
    assert int(np.unique(widths).size) >= 3


def test_normalized_fit_is_deterministic():
    rng = np.random.default_rng(2024)
    yt, yp, pv = _maxtraj_block(rng, 2000, sigma_lo=0.5, sigma_hi=2.5)
    c1 = fit_normalized_conformal(yt, yp, pv)
    c2 = fit_normalized_conformal(yt, yp, pv)
    assert (c1.c, c1.q_lo, c1.q_hi, c1.sigma_median, c1.sigma_floor) == (
        c2.c, c2.q_lo, c2.q_hi, c2.sigma_median, c2.sigma_floor
    )


def test_normalized_c_selection_prefers_in_band_then_closest():
    """With a tight band that no c can hit, fall back to the c closest to target."""
    rng = np.random.default_rng(5)
    yt, yp, pv = _maxtraj_block(rng, 2000, sigma_lo=0.8, sigma_hi=1.2)
    # An unreachable band forces the closest-to-target fallback (in_band False).
    cfg = NormalizedConformalConfig(band_lo=0.999, band_hi=1.0)
    cal = fit_normalized_conformal(yt, yp, pv, config=cfg)
    assert cal.in_band is False
    # closest pick minimizes |calib_cov - target| over the grid
    assert abs(cal.calib_coverage - cfg.coverage_target) <= 0.5


def test_prepare_sigma_sqrts_variance_imputes_and_floors():
    """Variance -> stddev via sqrt; None imputed with calib median; floored positive."""
    sigma, med, fl = _prepare_sigma([4.0, None, 9.0], is_variance=True)
    # sqrt(4)=2, sqrt(9)=3, median of finite {2,3} = 2.5 imputed for the None row
    assert sigma[0] == pytest.approx(2.0)
    assert sigma[2] == pytest.approx(3.0)
    assert sigma[1] == pytest.approx(2.5)
    assert med == pytest.approx(2.5)
    assert fl > 0.0
    assert np.all(sigma >= fl)


def test_prepare_sigma_reuses_passed_median_and_floor_on_apply():
    """apply path pins calib median/floor so no test statistic leaks back."""
    sigma, med, fl = _prepare_sigma([None, None], is_variance=True, median=2.0, floor=0.01)
    assert med == 2.0 and fl == 0.01
    assert np.all(sigma == 2.0)  # both imputed with the frozen calib median


def test_normalized_rejects_length_mismatch_and_empty():
    with pytest.raises(ValueError):
        fit_normalized_conformal([1, 2], [1.0], [1.0, 1.0])
    with pytest.raises(ValueError):
        fit_normalized_conformal([], [], [])


# --- Track A.A1: sigma winsorization (contracts/phase5_amendment.md) -----------
# The load-bearing properties: clip bounds are frozen on CALIB and REUSED on apply
# (no leakage from a different test sigma distribution); the path is deterministic;
# invariants hold (hi >= lo, int32, non-degenerate widths); and winsorize=False
# leaves the v1.0 calibrator byte-identical.


def _spiked_block(rng: np.random.Generator, n: int, *, tail_hi: float):
    """Spike-at-floor + heavy upper tail variance proxy (mimics p50_var)."""
    yp = rng.normal(15.0, 3.0, n)
    var = np.where(rng.random(n) < 0.75, 0.01, rng.uniform(0.05, tail_hi, n))
    std = np.sqrt(var)
    yt = np.floor(yp + rng.normal(0.0, 1.0, n) * std + 0.5).astype(int)
    return yt, yp, var.tolist()


def test_winsorize_off_is_v1_identical():
    """winsorize=False -> clip bounds None and the fit matches the default config."""
    rng = np.random.default_rng(1)
    yt, yp, var = _spiked_block(rng, 1500, tail_hi=1.2)
    base = fit_normalized_conformal(yt, yp, var)
    off = fit_normalized_conformal(yt, yp, var, config=NormalizedConformalConfig(winsorize=False))
    assert base.clip_lo is None and base.clip_hi is None
    assert (base.c, base.q_lo, base.q_hi) == (off.c, off.q_lo, off.q_hi)


def test_winsorize_freezes_calib_bounds_and_sets_them():
    rng = np.random.default_rng(2)
    yt, yp, var = _spiked_block(rng, 2000, tail_hi=1.2)
    cfg = NormalizedConformalConfig(winsorize=True, winsor_pctl_lo=25, winsor_pctl_hi=95)
    cal = fit_normalized_conformal(yt, yp, var, config=cfg)
    sig = _prepare_sigma(var, is_variance=True)[0]
    assert cal.clip_lo == pytest.approx(float(np.percentile(sig, 25)))
    assert cal.clip_hi == pytest.approx(float(np.percentile(sig, 95)))
    assert cal.clip_lo < cal.clip_hi


def test_winsorize_apply_reuses_calib_bounds_no_leak():
    """A test set with a MUCH higher sigma distribution must still be clipped at the
    calib-frozen clip_hi -- not at the test's own percentile (no leakage)."""
    rng = np.random.default_rng(3)
    yt_c, yp_c, var_c = _spiked_block(rng, 2000, tail_hi=1.0)
    cfg = NormalizedConformalConfig(winsorize=True, winsor_pctl_lo=25, winsor_pctl_hi=95)
    cal = fit_normalized_conformal(yt_c, yp_c, var_c, config=cfg)

    # Test rows with raw sigma far ABOVE the calib clip_hi.
    yp_t = np.full(50, 15.0)
    var_t = [(cal.clip_hi * 5.0) ** 2] * 50  # sqrt -> 5x the frozen clip_hi
    lo, hi = apply_normalized_conformal(cal, yp_t, var_t)

    # Expected: sigma clamped to calib clip_hi, so the interval equals the one built
    # from the frozen clip_hi -- NOT the wider one the raw (5x) sigma would give.
    sig_clamped = np.full(50, cal.clip_hi)
    exp_lo, exp_hi = _normalized_int_interval(yp_t, sig_clamped, cal.q_lo, cal.q_hi)
    assert np.array_equal(lo, exp_lo) and np.array_equal(hi, exp_hi)

    sig_raw = np.full(50, cal.clip_hi * 5.0)
    raw_lo, raw_hi = _normalized_int_interval(yp_t, sig_raw, cal.q_lo, cal.q_hi)
    assert (raw_hi - raw_lo).mean() > (hi - lo).mean()  # un-clipped would be wider


def test_winsorize_is_deterministic():
    rng = np.random.default_rng(4)
    yt, yp, var = _spiked_block(rng, 2000, tail_hi=1.2)
    cfg = NormalizedConformalConfig(winsorize=True)
    c1 = fit_normalized_conformal(yt, yp, var, config=cfg)
    c2 = fit_normalized_conformal(yt, yp, var, config=cfg)
    assert (c1.c, c1.q_lo, c1.q_hi, c1.clip_lo, c1.clip_hi) == (
        c2.c, c2.q_lo, c2.q_hi, c2.clip_lo, c2.clip_hi
    )


def test_winsorize_invariants_hold_and_widths_non_degenerate():
    rng = np.random.default_rng(5)
    yt, yp, var = _spiked_block(rng, 3000, tail_hi=2.0)
    cfg = NormalizedConformalConfig(winsorize=True)
    cal = fit_normalized_conformal(yt, yp, var, config=cfg)
    lo, hi = apply_normalized_conformal(cal, yp, var)
    assert lo.dtype == np.int32 and hi.dtype == np.int32
    assert np.all(hi >= lo)
    assert int(np.unique(hi - lo + 1).size) >= 3  # not collapsed to degenerate


def test_winsorize_sigma_helper_fit_then_reuse():
    s = np.array([0.01, 0.1, 0.1, 0.1, 0.3, 1.2])
    clipped, lo, hi = _winsorize_sigma(s, pctl_lo=25, pctl_hi=95)
    assert lo == pytest.approx(float(np.percentile(s, 25)))
    assert hi == pytest.approx(float(np.percentile(s, 95)))
    assert clipped.min() >= lo and clipped.max() <= hi
    # reuse path: passing bounds ignores the new array's own percentiles
    reused, rlo, rhi = _winsorize_sigma(np.array([99.0, 99.0]), pctl_lo=25, pctl_hi=95,
                                        clip_lo=lo, clip_hi=hi)
    assert rlo == lo and rhi == hi
    assert np.all(reused == hi)  # 99 clamped down to the frozen hi


# --- Track A.A3: Mondrian conditional conformal (phase5_amendment_trackA_a3.md) -----
# Load-bearing: the sigma-bucket partition (edges + deterministic merge) and the
# per-bucket SHRUNK quantiles are frozen on CALIB and reused on apply (no leak); the
# fit is deterministic; every surviving bucket is non-empty (>= min_n) post-merge;
# invariants hold (hi >= lo, int32, non-degenerate widths; q_eff lies between q_bucket
# and q_global); and a SINGLE surviving bucket reduces EXACTLY to v1.0.


def _spread_block(rng: np.random.Generator, n: int, *, sigma_lo: float, sigma_hi: float):
    """Continuous spread of sigma (as a variance proxy) so 4 quantile buckets survive."""
    yp = rng.normal(15.0, 3.0, n)
    std = rng.uniform(sigma_lo, sigma_hi, n)
    yt = np.floor(yp + rng.normal(0.0, 1.0, n) * std + 0.5).astype(int)
    return yt, yp, (std**2).tolist()


def test_mondrian_four_buckets_survive_under_spread_sigma():
    """A continuous sigma spread keeps all 4 quantile buckets above min_n (no merge)."""
    rng = np.random.default_rng(10)
    yt, yp, var = _spread_block(rng, 4000, sigma_lo=0.3, sigma_hi=3.0)
    cal = fit_mondrian_conformal(yt, yp, var)
    assert len(cal.edges) == 3  # 3 interior edges -> 4 buckets, none merged away
    assert len(cal.bucket_q_lo) == len(cal.bucket_q_hi) == len(cal.bucket_n) == 4
    assert all(n >= cal.config.min_n_bucket for n in cal.bucket_n)


def test_mondrian_spike_collapses_buckets_but_none_empty():
    """The sigma spike makes interior edges coincide; the merge collapses below 4
    buckets, and every surviving bucket still has >= min_n rows (none empty)."""
    rng = np.random.default_rng(11)
    yt, yp, var = _spiked_block(rng, 2000, tail_hi=1.2)
    cal = fit_mondrian_conformal(yt, yp, var)
    assert len(cal.edges) + 1 == len(cal.bucket_n)
    assert len(cal.bucket_n) < 4  # collapsed by the deterministic merge
    assert all(n >= cal.config.min_n_bucket for n in cal.bucket_n)


def test_mondrian_apply_reuses_calib_partition_no_leak():
    """A test set whose sigma sits entirely ABOVE the top calib edge must be assigned to
    the TOP bucket via the FROZEN edges, and use that bucket's frozen quantiles -- the
    test distribution never re-derives edges/buckets/quantiles."""
    rng = np.random.default_rng(12)
    yt, yp, var = _spread_block(rng, 4000, sigma_lo=0.3, sigma_hi=3.0)
    cal = fit_mondrian_conformal(yt, yp, var)

    top_sigma = cal.edges[-1] * 10.0
    yp_t = np.full(80, 15.0)
    var_t = [top_sigma**2] * 80
    lo, hi = apply_mondrian_conformal(cal, yp_t, var_t)

    sig_t = _prepare_sigma(
        var_t, is_variance=True, median=cal.sigma_median, floor=cal.sigma_floor
    )[0]
    top = len(cal.edges)  # highest bucket index
    exp_lo, exp_hi = _normalized_int_interval(
        yp_t, sig_t, cal.bucket_q_lo[top], cal.bucket_q_hi[top]
    )
    assert np.array_equal(lo, exp_lo) and np.array_equal(hi, exp_hi)

    # No-leak: re-deriving edges from the test sigma would NOT match the calib edges.
    test_edges = _mondrian_edges(sig_t, cal.config.edge_quantiles, cal.config.quantile_method)
    assert not np.allclose(test_edges, np.asarray(cal.edges, dtype=float))


def test_mondrian_fit_is_deterministic():
    rng = np.random.default_rng(13)
    yt, yp, var = _spread_block(rng, 3000, sigma_lo=0.3, sigma_hi=3.0)
    a = fit_mondrian_conformal(yt, yp, var)
    b = fit_mondrian_conformal(yt, yp, var)
    assert a.edges == b.edges
    assert a.bucket_q_lo == b.bucket_q_lo and a.bucket_q_hi == b.bucket_q_hi
    assert (a.c, a.bucket_n, a.q_lo_global, a.q_hi_global) == (
        b.c, b.bucket_n, b.q_lo_global, b.q_hi_global
    )


def test_mondrian_invariants_and_non_degenerate_widths():
    rng = np.random.default_rng(14)
    yt, yp, var = _spread_block(rng, 4000, sigma_lo=0.3, sigma_hi=3.0)
    cal = fit_mondrian_conformal(yt, yp, var)
    lo, hi = apply_mondrian_conformal(cal, yp, var)
    assert lo.dtype == np.int32 and hi.dtype == np.int32
    assert np.all(hi >= lo)
    assert int(np.unique(hi - lo + 1).size) >= 3
    assert all(n >= cal.config.min_n_bucket for n in cal.bucket_n)


def test_mondrian_shrinkage_q_eff_lies_between_bucket_and_global():
    """q_eff = a*q_bucket + (1-a)*q_global must lie between q_bucket and q_global."""
    rng = np.random.default_rng(15)
    yt, yp, var = _spread_block(rng, 4000, sigma_lo=0.3, sigma_hi=3.0)
    cal = fit_mondrian_conformal(yt, yp, var)
    sig = _prepare_sigma(var, is_variance=True)[0]
    u = (np.asarray(yt, dtype=float) - np.asarray(yp, dtype=float)) / sig
    buckets = _assign_buckets(sig, np.asarray(cal.edges, dtype=float), cal.config.searchsorted_side)
    p_hi = 1.0 - (1.0 - cal.c) / 2.0
    qg = float(np.quantile(u, p_hi, method=cal.config.quantile_method))
    assert cal.q_hi_global == pytest.approx(qg)
    for b in range(len(cal.bucket_n)):
        qb = float(np.quantile(u[buckets == b], p_hi, method=cal.config.quantile_method))
        qeff = cal.bucket_q_hi[b]
        assert min(qb, qg) - 1e-9 <= qeff <= max(qb, qg) + 1e-9


def test_mondrian_single_bucket_reduces_exactly_to_v1():
    """Forcing min_n above n collapses the partition to ONE bucket; then q_eff ==
    q_global and the emitted intervals are byte-identical to v1.0 normalized conformal."""
    rng = np.random.default_rng(16)
    yt, yp, var = _spread_block(rng, 3000, sigma_lo=0.5, sigma_hi=2.5)
    cfg = MondrianConformalConfig(min_n_bucket=10_000)  # > n -> everything merges to 1
    cal = fit_mondrian_conformal(yt, yp, var, config=cfg)
    assert cal.edges == () and len(cal.bucket_n) == 1
    assert cal.bucket_q_lo[0] == pytest.approx(cal.q_lo_global)
    assert cal.bucket_q_hi[0] == pytest.approx(cal.q_hi_global)

    v1 = fit_normalized_conformal(yt, yp, var)
    assert (cal.c, cal.bucket_q_lo[0], cal.bucket_q_hi[0]) == pytest.approx((v1.c, v1.q_lo, v1.q_hi))
    lo_m, hi_m = apply_mondrian_conformal(cal, yp, var)
    lo_v, hi_v = apply_normalized_conformal(v1, yp, var)
    assert np.array_equal(lo_m, lo_v) and np.array_equal(hi_m, hi_v)


def test_mondrian_merge_helper_drops_edges_until_all_ge_min_n():
    """The merge helper is deterministic and leaves no surviving bucket below min_n."""
    sigma = np.array([0.1] * 100 + [0.5] * 10 + [0.9] * 100, dtype=float)
    raw_edges = _mondrian_edges(sigma, (0.25, 0.50, 0.75), "linear")
    merged = _merge_edges_until_min_n(sigma, raw_edges, min_n=50, side="right")
    buckets = _assign_buckets(sigma, merged, "right")
    counts = [int((buckets == b).sum()) for b in range(merged.size + 1)]
    assert all(c >= 50 for c in counts)  # the 10-row middle bucket got merged away
    assert merged.size < raw_edges.size
