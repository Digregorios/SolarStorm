"""Residual LightGBM (T-4-4, design 8).

Target = ``truth - NWP_baseline_dec`` where ``NWP_baseline_dec`` is the
ensemble-mean ``nwp_t2m_at_cp_c`` (Phase 4 v1 anchor at CP). The residual
captures what the model fails to predict on the way to Tmax: morning warming
trajectory, regime-specific bias, etc.

Prediction: ``T_latent_dec = nwp_baseline + residual_pred``, then
``Q(T_latent_dec)`` for the integer.

Determinism: seeds fixed per ``REQ-MOD-6`` (random / numpy / lightgbm).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import lightgbm as lgb
import numpy as np

from core.contracts.quantization import Q
from core.models.loss import band_aware_loss, latent_to_prob_dist


@dataclass(frozen=True)
class ResidualLgbmConfig:
    feature_columns: tuple[str, ...]
    n_estimators: int = 500
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_data_in_leaf: int = 20
    feature_fraction: float = 0.9
    bagging_fraction: float = 0.9
    bagging_freq: int = 1
    seed: int = 42
    early_stopping_rounds: int = 30
    tau: float = 0.5
    mode: str = "linear"
    val_frac: float = 0.2


@dataclass
class FittedResidualLgbm:
    booster: lgb.Booster
    feature_columns: tuple[str, ...]
    nwp_anchor_column: str  # column name carrying the NWP baseline (e.g. "nwp_t2m_at_cp_c")
    tau: float
    mode: str
    n_features: int
    train_n: int
    best_iteration: int
    feature_means_for_imputation: np.ndarray


def _impute_nan(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Same pure helper as Ridge - mean impute on a copy."""
    import warnings

    out = X.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        col_means = np.nanmean(out, axis=0)
    col_means = np.where(np.isnan(col_means), 0.0, col_means)
    inds = np.where(np.isnan(out))
    out[inds] = np.take(col_means, inds[1])
    return out, col_means


def fit_residual_lgbm(
    X_train: np.ndarray,
    y_train_int: np.ndarray,
    nwp_anchor_train: np.ndarray,
    *,
    config: ResidualLgbmConfig,
) -> FittedResidualLgbm:
    """Fit LightGBM on residual = truth - NWP_anchor."""
    n = X_train.shape[0]
    if n < 100:
        raise ValueError(f"Need >= 100 train rows; got {n}")
    if nwp_anchor_train.shape[0] != n:
        raise ValueError("nwp_anchor_train length mismatch")

    # Impute NaN in features (LightGBM also handles NaN natively but we
    # standardise behaviour with Ridge).
    X_imp, col_means = _impute_nan(X_train)
    # NWP anchor: forward-fill missing with running mean of valid anchors;
    # rows with no anchor get residual_target = 0 fallback (model effectively
    # falls back to predict NWP itself).
    anchor = np.asarray(nwp_anchor_train, dtype=float).copy()
    valid = ~np.isnan(anchor)
    if valid.sum() == 0:
        raise ValueError("No valid NWP anchor in training set")
    fill_value = float(np.mean(anchor[valid]))
    anchor[~valid] = fill_value
    residual_target = y_train_int.astype(float) - anchor

    n_val = max(50, int(round(n * config.val_frac)))
    n_fit = n - n_val
    if n_fit < 50:
        raise ValueError("Not enough rows after carving out validation tail.")

    X_fit, X_val = X_imp[:n_fit], X_imp[n_fit:]
    y_fit, y_val = residual_target[:n_fit], residual_target[n_fit:]

    train_set = lgb.Dataset(X_fit, label=y_fit)
    valid_set = lgb.Dataset(X_val, label=y_val, reference=train_set)

    params = {
        "objective": "regression",
        "metric": "rmse",
        "learning_rate": config.learning_rate,
        "num_leaves": config.num_leaves,
        "min_data_in_leaf": config.min_data_in_leaf,
        "feature_fraction": config.feature_fraction,
        "bagging_fraction": config.bagging_fraction,
        "bagging_freq": config.bagging_freq,
        "verbose": -1,
        "seed": config.seed,
        "bagging_seed": config.seed,
        "feature_fraction_seed": config.seed,
        "drop_seed": config.seed,
        "deterministic": True,
        "force_col_wise": True,
        "num_threads": 1,
    }

    booster = lgb.train(
        params=params,
        train_set=train_set,
        num_boost_round=config.n_estimators,
        valid_sets=[valid_set],
        valid_names=["val"],
        callbacks=[
            lgb.early_stopping(stopping_rounds=config.early_stopping_rounds, verbose=False),
            lgb.log_evaluation(period=0),
        ],
    )
    best_iter = booster.best_iteration
    return FittedResidualLgbm(
        booster=booster,
        feature_columns=config.feature_columns,
        nwp_anchor_column="nwp_t2m_at_cp_c",
        tau=config.tau,
        mode=config.mode,
        n_features=X_train.shape[1],
        train_n=int(n),
        best_iteration=int(best_iter or config.n_estimators),
        feature_means_for_imputation=col_means,
    )


def predict_latent(
    model: FittedResidualLgbm,
    X: np.ndarray,
    nwp_anchor: np.ndarray,
) -> np.ndarray:
    Xc = X.copy()
    inds = np.where(np.isnan(Xc))
    if inds[0].size:
        Xc[inds] = np.take(model.feature_means_for_imputation, inds[1])
    residual = model.booster.predict(Xc, num_iteration=model.best_iteration)
    anchor = np.asarray(nwp_anchor, dtype=float).copy()
    valid = ~np.isnan(anchor)
    if (~valid).any():
        if valid.any():
            anchor[~valid] = float(np.mean(anchor[valid]))
        else:
            anchor[~valid] = 0.0
    return anchor + residual


def predict_int(
    model: FittedResidualLgbm, X: np.ndarray, nwp_anchor: np.ndarray
) -> np.ndarray:
    latent = predict_latent(model, X, nwp_anchor)
    return np.array([Q(float(v)) for v in latent], dtype=np.int32)


def predict_dist(
    model: FittedResidualLgbm,
    X: np.ndarray,
    nwp_anchor: np.ndarray,
    support_k_per_row: Iterable[Iterable[int]],
) -> list[dict[int, float]]:
    latents = predict_latent(model, X, nwp_anchor)
    out: list[dict[int, float]] = []
    for v, sk in zip(latents, support_k_per_row, strict=True):
        out.append(
            latent_to_prob_dist(float(v), list(sk), tau=model.tau, mode=model.mode)
        )
    return out


__all__ = [
    "ResidualLgbmConfig",
    "FittedResidualLgbm",
    "fit_residual_lgbm",
    "predict_latent",
    "predict_int",
    "predict_dist",
]
