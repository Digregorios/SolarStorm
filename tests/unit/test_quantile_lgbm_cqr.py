"""Synthetic correctness tests for the CQR quantile-LightGBM model (T-11-8, Phase 4).

These tests pin the conformal *algorithm* on controlled synthetic data BEFORE the
model is ever run on the real panel (anti-gaming: structure + synthetic checks first,
freeze the gate last). They do NOT use the frozen evaluation hyperparameters -- a small
tree budget is used for speed; the conformal guarantee is independent of the quantile
model's quality, which is exactly the CQR property under test.

Pinned invariants:
  1. conformity rank == ceil((n+1)*coverage) on the sorted REAL-VALUED scores;
  2. the score is NOT abs'd (a negative E flows through and shrinks an over-covering band);
  3. a too-small calib set clamps the rank and reports certified=False;
  4. marginal coverage ~ target on exchangeable heteroscedastic data;
  5. determinism: same seed -> byte-identical bounds and E;
  6. hi >= lo always;
  7. integer rounding happens ONLY at the end (predictions/E stay decimal; IC is int32).
"""

from __future__ import annotations

import math

import numpy as np

from core.models.quantile_lgbm import (
    CqrCalibrator,
    QuantileLgbmConfig,
    _conformal_quantile,
    conformalize,
    fit_quantile_lgbm,
    predict_dist,
    predict_interval_int,
    predict_median,
    predict_quantiles,
)


def _make_hetero_data(
    n: int, rng: np.random.Generator, *, n_features: int = 4
) -> tuple[np.ndarray, np.ndarray]:
    """i.i.d. heteroscedastic regression draws (exchangeable across any split)."""
    X = rng.normal(0.0, 1.0, size=(n, n_features))
    signal = 20.0 + 4.0 * X[:, 0] + 2.0 * np.sin(X[:, 1])
    sigma = 0.5 + 0.8 * np.abs(X[:, 2])  # noise scale varies with a feature
    noise = rng.normal(0.0, 1.0, size=n) * sigma
    y_int = np.rint(signal + noise).astype(np.int32)
    return X.astype(float), y_int


def _cfg(n_features: int, *, fit_median: bool = False) -> QuantileLgbmConfig:
    """Small, fast booster budget for synthetic tests (NOT the frozen eval config)."""
    return QuantileLgbmConfig(
        feature_columns=tuple(f"f{i}" for i in range(n_features)),
        n_estimators=80,
        num_leaves=15,
        min_data_in_leaf=10,
        early_stopping_rounds=20,
        fit_median=fit_median,
    )


# --------------------------------------------------------------------------- #
# 1-3: the conformal-quantile primitive (pure, deterministic)                 #
# --------------------------------------------------------------------------- #
def test_conformal_rank_is_ceil_n_plus_1_coverage():
    # n=9, cov=0.80 -> rank=ceil(10*0.8)=8 -> idx 7 -> value 7.0 (certified).
    scores = np.arange(9, dtype=float)
    e, certified = _conformal_quantile(scores, 0.80)
    assert e == 7.0 and certified is True
    # cross-check the closed form for a spread of (n, coverage) pairs.
    for n in (5, 9, 13, 40, 199):
        for cov in (0.70, 0.80, 0.90):
            s = np.arange(n, dtype=float)
            rank = int(math.ceil((n + 1) * cov))
            idx = min(max(rank, 1), n) - 1
            val, cert = _conformal_quantile(s, cov)
            assert val == float(s[idx])
            assert cert is (rank <= n)


def test_conformal_score_not_absed_negative_E_allowed():
    # All scores negative (nominal band over-covers): E must stay negative, not abs'd.
    scores = np.array([-3.0, -2.0, -1.0])
    e, certified = _conformal_quantile(scores, 0.80)  # n=3 -> rank=4 (clamped)
    assert e == -1.0
    assert certified is False  # rank 4 > n 3


def test_conformal_unsorted_input_is_sorted_internally():
    e1, _ = _conformal_quantile(np.array([2.0, 0.0, 1.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]), 0.80)
    e2, _ = _conformal_quantile(np.arange(9, dtype=float), 0.80)
    assert e1 == e2 == 7.0


# --------------------------------------------------------------------------- #
# 4: marginal coverage on exchangeable heteroscedastic data                   #
# --------------------------------------------------------------------------- #
def test_marginal_coverage_on_exchangeable_data():
    rng = np.random.default_rng(7)
    X_tr, y_tr = _make_hetero_data(700, rng)
    X_ca, y_ca = _make_hetero_data(500, rng)
    X_te, y_te = _make_hetero_data(2000, rng)

    model = fit_quantile_lgbm(X_tr, y_tr, config=_cfg(X_tr.shape[1]))
    cal = conformalize(model, X_ca, y_ca)
    lo, hi = predict_interval_int(model, cal, X_te)

    cov = float(np.mean((y_te >= lo) & (y_te <= hi)))
    # CQR marginal guarantee is ~ (1-alpha)=0.80; allow finite-sample slack either way.
    # Lower bound 0.74 = guarantee minus ~3-sigma slack; upper 0.95 rejects gross
    # over-covering. Band is PRINCIPLED, not tuned to the observed value.
    assert 0.74 <= cov <= 0.95
    assert bool((hi >= lo).all())


# --------------------------------------------------------------------------- #
# 5: determinism (byte-identical bounds and E under a fixed seed)             #
# --------------------------------------------------------------------------- #
def test_determinism_byte_identical():
    rng = np.random.default_rng(11)
    X_tr, y_tr = _make_hetero_data(300, rng)
    X_ca, y_ca = _make_hetero_data(200, rng)
    X_te, y_te = _make_hetero_data(150, rng)
    cfg = _cfg(X_tr.shape[1])

    m1 = fit_quantile_lgbm(X_tr, y_tr, config=cfg)
    c1 = conformalize(m1, X_ca, y_ca)
    lo1, hi1 = predict_interval_int(m1, c1, X_te)

    m2 = fit_quantile_lgbm(X_tr, y_tr, config=cfg)
    c2 = conformalize(m2, X_ca, y_ca)
    lo2, hi2 = predict_interval_int(m2, c2, X_te)

    assert c1.e_correction == c2.e_correction
    assert np.array_equal(lo1, lo2)
    assert np.array_equal(hi1, hi2)


# --------------------------------------------------------------------------- #
# 6: hi >= lo always, including when E shrinks an over-covering band          #
# --------------------------------------------------------------------------- #
def test_negative_E_shrinks_band_and_keeps_order():
    rng = np.random.default_rng(3)
    X_tr, y_tr = _make_hetero_data(400, rng)
    X_te, _ = _make_hetero_data(300, rng)
    model = fit_quantile_lgbm(X_tr, y_tr, config=_cfg(X_tr.shape[1]))

    zero = CqrCalibrator(e_correction=0.0, n_calib=100, certified=True, coverage=0.80)
    neg = CqrCalibrator(e_correction=-2.0, n_calib=100, certified=True, coverage=0.80)

    lo0, hi0 = predict_interval_int(model, zero, X_te)
    lon, hin = predict_interval_int(model, neg, X_te)

    assert bool((hi0 >= lo0).all()) and bool((hin >= lon).all())
    # A negative correction can only narrow (or, after the hi>=lo clamp, equal) the band.
    assert bool(((hin - lon) <= (hi0 - lo0)).all())
    assert int((hin - lon).sum()) < int((hi0 - lo0).sum())


# --------------------------------------------------------------------------- #
# 7: round-at-the-end discipline (T-9-5 lesson)                               #
# --------------------------------------------------------------------------- #
def test_round_at_end_predictions_decimal_interval_integer():
    rng = np.random.default_rng(5)
    X_tr, y_tr = _make_hetero_data(400, rng)
    X_ca, y_ca = _make_hetero_data(300, rng)
    X_te, _ = _make_hetero_data(200, rng)
    model = fit_quantile_lgbm(X_tr, y_tr, config=_cfg(X_tr.shape[1]))

    q_lo, q_hi = predict_quantiles(model, X_te)
    assert q_lo.dtype == float and q_hi.dtype == float
    # raw quantile predictions are genuinely decimal (not pre-quantized to int).
    assert np.any(np.abs(q_lo - np.rint(q_lo)) > 1e-6)

    cal = conformalize(model, X_ca, y_ca)
    assert isinstance(cal.e_correction, float)

    lo, hi = predict_interval_int(model, cal, X_te)
    assert lo.dtype == np.int32 and hi.dtype == np.int32
    assert np.array_equal(lo, lo.astype(np.int64))  # exact integers
    assert np.array_equal(hi, hi.astype(np.int64))


# --------------------------------------------------------------------------- #
# median center for the RPS / point guardrail (prereg gate conditions 4-5)    #
# --------------------------------------------------------------------------- #
def test_median_center_and_prob_dist():
    rng = np.random.default_rng(9)
    X_tr, y_tr = _make_hetero_data(400, rng)
    X_te, _ = _make_hetero_data(20, rng)
    model = fit_quantile_lgbm(X_tr, y_tr, config=_cfg(X_tr.shape[1], fit_median=True))

    centers = predict_median(model, X_te)
    assert centers.dtype == float and centers.shape == (20,)

    support = [list(range(int(c) - 3, int(c) + 4)) for c in np.rint(centers)]
    dists = predict_dist(model, X_te, support)
    assert len(dists) == 20
    for d in dists:
        assert abs(sum(d.values()) - 1.0) < 1e-9
        assert all(p >= 0.0 for p in d.values())
