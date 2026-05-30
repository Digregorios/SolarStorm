"""Regression test: i_t_obs permutation importance must score the ANCHORED model.

Bug (pre-fix): scripts/phase4_evaluate.py fed ``clim_test`` to ``predict_latent``
inside the permutation-importance lambda, while the LGBM was fit on
``target = truth - nwp_anchor``. ``predict_latent`` returns ``anchor + residual``, so
using climatology as the anchor audits a mis-anchored model and silently corrupts the
REQ-AUD-2 I_T_obs verdict. The fix routes the model's OWN ``nwp_anchor_test`` through,
and ``compute_i_t_obs`` makes the anchor a required positional arg.
"""

from __future__ import annotations

import numpy as np

from core.eval.permutation import permutation_importance
from core.models.residual_lgbm import (
    ResidualLgbmConfig,
    fit_residual_lgbm,
    predict_latent,
)
from scripts.phase4_evaluate import compute_i_t_obs


def _fit_synthetic_model(seed: int = 0):
    """Fit a residual LGBM where the anchor carries most of the signal."""
    rng = np.random.default_rng(seed)
    n = 400
    n_features = 6
    last_obs_idx = 3
    X = rng.normal(size=(n, n_features))
    # NWP anchor is the dominant predictor of truth; the residual is a small
    # function of a NON-last_obs feature, so last_obs has near-zero true importance.
    anchor = rng.normal(18.0, 4.0, size=n)
    residual = 1.2 * X[:, 0] + rng.normal(0, 0.3, size=n)
    truth = (anchor + residual).round().astype(int)
    cfg = ResidualLgbmConfig(
        feature_columns=tuple(f"f{i}" for i in range(n_features)),
        n_estimators=120,
        learning_rate=0.05,
        num_leaves=15,
        min_data_in_leaf=20,
    )
    model = fit_residual_lgbm(X, truth, anchor, config=cfg)
    return model, X, truth, anchor, last_obs_idx


def test_compute_i_t_obs_matches_manual_permutation_with_anchor():
    """compute_i_t_obs must equal a hand-rolled permutation that uses the NWP anchor."""
    model, X, truth, anchor, last_obs_idx = _fit_synthetic_model()

    got = compute_i_t_obs(model, X, truth, anchor, last_obs_idx, n_repeats=5, seed=42)

    truth_var = float(np.var(truth.astype(float))) or 1.0

    def r2(yp, yt):
        return 1.0 - float(np.mean((yp - yt) ** 2)) / truth_var

    expected = permutation_importance(
        X=X.copy(),
        y=truth.astype(float),
        feature_index=last_obs_idx,
        score=r2,
        predict=lambda Xq: predict_latent(model, Xq, anchor),
        n_repeats=5,
        seed=42,
    )
    assert got == expected


def test_compute_i_t_obs_differs_from_wrong_anchor():
    """Routing climatology (wrong) vs the NWP anchor (right) must yield different
    importances -> proves the anchor is actually wired through, not ignored."""
    model, X, truth, anchor, last_obs_idx = _fit_synthetic_model()
    # A 'climatology'-like series, deliberately offset from the true anchor.
    clim = np.full_like(anchor, float(np.mean(truth)))

    correct = compute_i_t_obs(model, X, truth, anchor, last_obs_idx, n_repeats=5, seed=42)

    truth_var = float(np.var(truth.astype(float))) or 1.0

    def r2(yp, yt):
        return 1.0 - float(np.mean((yp - yt) ** 2)) / truth_var

    wrong = permutation_importance(
        X=X.copy(),
        y=truth.astype(float),
        feature_index=last_obs_idx,
        score=r2,
        predict=lambda Xq: predict_latent(model, Xq, clim),  # the OLD bug
        n_repeats=5,
        seed=42,
    )
    assert not np.isclose(correct, wrong), (
        "i_t_obs is invariant to the anchor series -> the anchor is not being used"
    )
