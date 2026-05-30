"""Confidence score tests (design 8.3 / REQ-CONF-1..2).

The load-bearing properties:
- the score is INFORMATIVE -- selective ``bracket_match`` on the most-confident rows
  beats overall accuracy (the risk-coverage promise, REQ-CONF-1 table);
- it is reasonably CALIBRATED in-sample (isotonic), with ECE reported;
- the optional signals (``nwp_spread``, ``p50_var``) degrade gracefully when absent;
- the fit is DETERMINISTIC (lbfgs + PAVA, no RNG -> REQ-MOD-6) and validates inputs.

Synthetic DGP: a latent skill ``s`` drives both ``P(bracket_correct)`` and all five
phi signals monotonically, so an honest confidence model must rank rows by ``s``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from core.confidence.score import (
    ConfidenceConfig,
    ConfidenceReport,
    bracket_match_by_coverage,
    confidence_report,
    confidence_score,
    distance_to_threshold,
    ece,
    entropy,
    fit_confidence,
)


def _dgp(rng: np.random.Generator, n: int):
    """Latent-skill DGP: higher ``s`` -> more often correct AND every phi signal stronger."""
    s = rng.normal(0.0, 1.0, n)
    p_corr = 1.0 / (1.0 + np.exp(-1.5 * s))
    correct = (rng.random(n) < p_corr).astype(int)

    base_k = 15
    peak = np.clip(0.50 + 0.15 * s, 0.34, 0.95)  # sharper dist with s -> lower entropy
    prob_dist = []
    for pk in peak:
        rest = (1.0 - float(pk)) / 2.0
        prob_dist.append({base_k - 1: rest, base_k: float(pk), base_k + 1: rest})

    width = np.clip(np.round(4.0 - s), 1, 8).astype(int)  # narrower IC with s
    ic_lo = (base_k - width // 2).astype(int)
    ic_hi = (ic_lo + width).astype(int)

    spread = np.clip(2.0 - 0.5 * s, 0.05, None)  # tighter ensemble with s
    pvar = np.clip(1.5 - 0.4 * s, 0.01, None)  # steadier CP-to-CP with s

    t = np.clip(0.05 + 0.40 / (1.0 + np.exp(-s)), 0.02, 0.49)  # dist-to-threshold target
    p50_dec = base_k + (0.5 - t)  # frac in (0.01, 0.48] -> stays in bracket base_k

    return dict(
        prob_dist=prob_dist,
        ic_lo=ic_lo.tolist(),
        ic_hi=ic_hi.tolist(),
        p50_dec=p50_dec.tolist(),
        correct=correct.tolist(),
        spread=spread.tolist(),
        pvar=pvar.tolist(),
        s=s,
    )


# --- phi primitives -----------------------------------------------------------

def test_entropy_point_mass_and_uniform():
    assert entropy({15: 1.0}) == 0.0
    assert entropy({15: 0.5, 16: 0.5}) == pytest.approx(math.log(2))
    assert entropy({14: 1 / 3, 15: 1 / 3, 16: 1 / 3}) == pytest.approx(math.log(3))


def test_distance_to_threshold_center_edge_and_seam():
    assert distance_to_threshold(15.0) == pytest.approx(0.5)  # bracket center
    assert distance_to_threshold(14.75) == pytest.approx(0.25)
    assert distance_to_threshold(15.49) == pytest.approx(0.01, abs=1e-9)
    assert distance_to_threshold(15.5) == pytest.approx(0.0)  # exactly on a seam


# --- informative + calibrated -------------------------------------------------

def test_confidence_is_informative_and_calibrated():
    rng = np.random.default_rng(42)
    d = _dgp(rng, 4000)
    fitted = fit_confidence(
        d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"], d["correct"],
        nwp_spread=d["spread"], p50_var=d["pvar"],
    )
    conf = confidence_score(
        fitted, d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"],
        nwp_spread=d["spread"], p50_var=d["pvar"],
    )
    assert conf.min() >= 0.0 and conf.max() <= 1.0
    # confidence ranks by latent skill
    assert float(np.corrcoef(conf, d["s"])[0, 1]) > 0.4
    # selective accuracy: top quartile clearly beats the field (risk-coverage promise)
    bm = bracket_match_by_coverage(conf, d["correct"])
    assert bm[0.25][0] > bm[1.0][0]
    assert bm[0.25][0] > 0.70
    # in-sample isotonic keeps ECE small (the 0.05 gate is a hold-out audit, not here)
    assert ece(conf, d["correct"]) <= 0.10


def test_optional_signals_absent_degrades_gracefully():
    """No NWP and no CP history (both optional signals None) still fits and scores."""
    rng = np.random.default_rng(7)
    d = _dgp(rng, 2000)
    fitted = fit_confidence(
        d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"], d["correct"],
        nwp_spread=None, p50_var=None,
    )
    # the two missing columns are neutralized: zero mean, unit (clamped) std
    assert fitted.feat_means[2] == 0.0 and fitted.feat_means[3] == 0.0
    assert fitted.feat_stds[2] == 1.0 and fitted.feat_stds[3] == 1.0
    conf = confidence_score(
        fitted, d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"]
    )
    assert conf.min() >= 0.0 and conf.max() <= 1.0
    bm = bracket_match_by_coverage(conf, d["correct"])
    assert bm[0.25][0] >= bm[1.0][0]  # still informative on the 3 surviving signals


def test_partial_missing_nwp_spread_is_imputed():
    rng = np.random.default_rng(3)
    d = _dgp(rng, 1500)
    spread = list(d["spread"])
    for i in range(0, len(spread), 5):  # 20% missing
        spread[i] = None
    fitted = fit_confidence(
        d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"], d["correct"],
        nwp_spread=spread, p50_var=d["pvar"],
    )
    conf = confidence_score(
        fitted, d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"],
        nwp_spread=spread, p50_var=d["pvar"],
    )
    assert conf.min() >= 0.0 and conf.max() <= 1.0
    assert math.isfinite(fitted.feat_means[2])  # imputed from the observed spreads


def test_isotonic_disabled_path():
    rng = np.random.default_rng(9)
    d = _dgp(rng, 1500)
    fitted = fit_confidence(
        d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"], d["correct"],
        config=ConfidenceConfig(isotonic=False),
    )
    assert fitted.isotonic is None
    conf = confidence_score(fitted, d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"])
    assert conf.min() >= 0.0 and conf.max() <= 1.0


# --- determinism (REQ-MOD-6) --------------------------------------------------

def test_fit_is_deterministic():
    rng = np.random.default_rng(2024)
    d = _dgp(rng, 1200)
    args = (d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"], d["correct"])
    kw = dict(nwp_spread=d["spread"], p50_var=d["pvar"])
    f1 = fit_confidence(*args, **kw)
    f2 = fit_confidence(*args, **kw)
    assert np.array_equal(f1.logistic.coef_, f2.logistic.coef_)
    assert np.array_equal(f1.logistic.intercept_, f2.logistic.intercept_)
    c1 = confidence_score(f1, d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"], **kw)
    c2 = confidence_score(f2, d["prob_dist"], d["ic_lo"], d["ic_hi"], d["p50_dec"], **kw)
    assert np.array_equal(c1, c2)


# --- audit metrics ------------------------------------------------------------

def test_bracket_match_by_coverage_ranks_and_validates():
    conf = [0.9, 0.8, 0.2, 0.1]
    correct = [1, 1, 0, 0]
    out = bracket_match_by_coverage(conf, correct, coverages=(0.25, 0.5, 1.0))
    assert out[0.25] == (1.0, 1)
    assert out[0.5] == (1.0, 2)
    assert out[1.0] == (0.5, 4)
    with pytest.raises(ValueError):
        bracket_match_by_coverage(conf, correct, coverages=(1.5,))


def test_ece_zero_when_calibrated_large_when_overconfident():
    # perfectly calibrated: predict 0.5, observe 50/50 in that bin -> ECE 0
    cal_conf = [0.5] * 100
    cal_correct = [1] * 50 + [0] * 50
    assert ece(cal_conf, cal_correct) == pytest.approx(0.0, abs=1e-9)
    # pathologically over-confident: predict ~1.0, always wrong -> ECE ~1.0
    bad_conf = [0.99] * 100
    bad_correct = [0] * 100
    assert ece(bad_conf, bad_correct) > 0.9


def test_confidence_report_fields_and_within_tol():
    rep = confidence_report([0.5] * 100, [1] * 50 + [0] * 50)
    assert isinstance(rep, ConfidenceReport)
    assert rep.ece == pytest.approx(0.0, abs=1e-9)
    assert rep.ece_within_tol is True  # 0 <= 0.05
    assert rep.n == 100
    assert rep.bracket_match_by_coverage[1.0] == (0.5, 100)

    bad = confidence_report([0.99] * 100, [0] * 100)
    assert bad.ece_within_tol is False  # ~1.0 > 0.05


# --- input validation ---------------------------------------------------------

def test_fit_rejects_degenerate_labels_and_mismatch():
    pd = [{15: 1.0}, {15: 0.5, 16: 0.5}]
    with pytest.raises(ValueError):  # single class
        fit_confidence(pd, [14, 14], [16, 16], [15.0, 15.0], [1, 1])
    with pytest.raises(ValueError):  # non-binary label
        fit_confidence(pd, [14, 14], [16, 16], [15.0, 15.0], [0, 2])
    with pytest.raises(ValueError):  # length mismatch
        fit_confidence(pd, [14], [16, 16], [15.0, 15.0], [0, 1])
    with pytest.raises(ValueError):  # empty
        fit_confidence([], [], [], [], [])


def test_metric_helpers_reject_empty_and_mismatch():
    with pytest.raises(ValueError):
        ece([], [])
    with pytest.raises(ValueError):
        ece([0.5, 0.6], [1])
    with pytest.raises(ValueError):
        bracket_match_by_coverage([], [])
