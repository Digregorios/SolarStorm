"""Determinism CI gate (REQ-MOD-6; prereg seeds frozen at 42, omp_num_threads=1).

Two independent trainings of the residual LightGBM on identical data MUST yield
byte-identical predictions. We assert both array-equality and an identical sha256
of the prediction vector - the same hash discipline the pre-registration uses, so a
future change that silently introduces nondeterminism (threading, unseeded RNG,
hash-ordering) trips this gate instead of quietly perturbing the Phase 4 verdict.
"""

from __future__ import annotations

import numpy as np

from core.io.hashing import sha256_text
from core.models.residual_lgbm import (
    ResidualLgbmConfig,
    fit_residual_lgbm,
    predict_latent,
)


def _synthetic(n: int = 400, n_features: int = 8, seed: int = 0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, n_features))
    anchor = rng.normal(15.0, 4.0, size=n)
    # truth = anchor + a learnable signal + noise, rounded to int (Tmax is integer).
    truth = (anchor + X[:, 0] * 1.5 + X[:, 1] * 0.5 + rng.normal(0, 0.5, size=n))
    truth_int = np.round(truth).astype(int)
    return X, truth_int, anchor


def _hash_preds(p: np.ndarray) -> str:
    # Fixed-precision text so the hash is stable across platforms but sensitive to
    # any real change in the predicted latent values.
    return sha256_text("\n".join(f"{v:.10f}" for v in p) + "\n")


def test_residual_lgbm_two_trainings_are_bit_identical():
    X, truth_int, anchor = _synthetic()
    cfg = ResidualLgbmConfig(feature_columns=tuple(f"f{i}" for i in range(X.shape[1])))

    m1 = fit_residual_lgbm(X, truth_int, anchor, config=cfg)
    m2 = fit_residual_lgbm(X, truth_int, anchor, config=cfg)

    p1 = predict_latent(m1, X, anchor)
    p2 = predict_latent(m2, X, anchor)

    assert np.array_equal(p1, p2), "residual LGBM is nondeterministic across trainings"
    assert _hash_preds(p1) == _hash_preds(p2)
    assert m1.best_iteration == m2.best_iteration


def test_residual_lgbm_prediction_is_repeatable_for_same_model():
    X, truth_int, anchor = _synthetic(seed=7)
    cfg = ResidualLgbmConfig(feature_columns=tuple(f"f{i}" for i in range(X.shape[1])))
    m = fit_residual_lgbm(X, truth_int, anchor, config=cfg)
    assert _hash_preds(predict_latent(m, X, anchor)) == _hash_preds(predict_latent(m, X, anchor))
