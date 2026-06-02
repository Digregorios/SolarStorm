"""MOS/EMOS-lite post-processing for causal NWP anchors.

This module is intentionally small: it fits a linear MOS center and a single
train-only residual scale, then emits a discrete Gaussian-like probability
distribution over the project support. It is an offline Track-C candidate, not a
serving promotion by itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable

import numpy as np
from sklearn.linear_model import Ridge

from core.contracts.quantization import Q


@dataclass(frozen=True)
class MosEmosLiteConfig:
    feature_columns: tuple[str, ...]
    alpha: float = 1.0
    min_sigma: float = 0.75
    sigma_floor_quantile: float = 0.80
    seed: int = 42


@dataclass(frozen=True)
class FittedMosEmosLite:
    ridge: Ridge
    feature_columns: tuple[str, ...]
    feature_means: np.ndarray
    feature_stds: np.ndarray
    sigma: float
    alpha: float
    train_n: int


def _impute_nan(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import warnings

    out = X.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        col_means = np.nanmean(out, axis=0)
    col_means = np.where(np.isnan(col_means), 0.0, col_means)
    inds = np.where(np.isnan(out))
    out[inds] = np.take(col_means, inds[1])
    return out, col_means


def _standardise(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    safe = np.where(std == 0.0, 1.0, std)
    return (X - mean) / safe


def fit_mos_emos_lite(
    X_train: np.ndarray,
    y_train_int: np.ndarray,
    *,
    config: MosEmosLiteConfig,
) -> FittedMosEmosLite:
    """Fit the MOS center and train-only EMOS-lite residual scale."""
    n = X_train.shape[0]
    if n < 100:
        raise ValueError(f"Need >= 100 train rows; got {n}")
    if y_train_int.shape[0] != n:
        raise ValueError("y_train_int length mismatch")
    if not 0.0 < config.sigma_floor_quantile <= 1.0:
        raise ValueError("sigma_floor_quantile must be in (0, 1]")
    if config.min_sigma <= 0.0:
        raise ValueError("min_sigma must be > 0")

    X_imp, col_means = _impute_nan(X_train)
    mean = X_imp.mean(axis=0)
    std = X_imp.std(axis=0)
    X_std = _standardise(X_imp, mean, std)

    ridge = Ridge(alpha=config.alpha, random_state=config.seed)
    ridge.fit(X_std, y_train_int.astype(float))
    center = ridge.predict(X_std)
    abs_resid = np.abs(y_train_int.astype(float) - center)
    sigma = max(
        float(config.min_sigma),
        float(np.quantile(abs_resid, config.sigma_floor_quantile)),
    )
    return FittedMosEmosLite(
        ridge=ridge,
        feature_columns=config.feature_columns,
        feature_means=mean,
        feature_stds=std,
        sigma=sigma,
        alpha=float(config.alpha),
        train_n=int(n),
    )


def calibrate_sigma(
    model: FittedMosEmosLite,
    X_calib: np.ndarray,
    y_calib_int: np.ndarray,
    *,
    config: MosEmosLiteConfig,
) -> FittedMosEmosLite:
    """Replace ``sigma`` with a calibration-tail residual scale."""
    if X_calib.shape[0] < 20:
        raise ValueError(f"Need >= 20 calibration rows; got {X_calib.shape[0]}")
    if y_calib_int.shape[0] != X_calib.shape[0]:
        raise ValueError("y_calib_int length mismatch")
    center = predict_latent(model, X_calib)
    abs_resid = np.abs(y_calib_int.astype(float) - center)
    sigma = max(
        float(config.min_sigma),
        float(np.quantile(abs_resid, config.sigma_floor_quantile)),
    )
    return replace(model, sigma=sigma)


def predict_latent(model: FittedMosEmosLite, X: np.ndarray) -> np.ndarray:
    Xc = X.copy()
    inds = np.where(np.isnan(Xc))
    if inds[0].size:
        Xc[inds] = np.take(model.feature_means, inds[1])
    return model.ridge.predict(_standardise(Xc, model.feature_means, model.feature_stds))


def gaussian_discrete_dist(center: float, support_k: Iterable[int], *, sigma: float) -> dict[int, float]:
    """Discretise a Gaussian EMOS-lite forecast over integer brackets."""
    if sigma <= 0.0:
        raise ValueError("sigma must be > 0")
    support = list(support_k)
    if not support:
        raise ValueError("support_k must be non-empty")

    def _cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf((x - float(center)) / (float(sigma) * math.sqrt(2.0))))

    weights = [_cdf(float(k) + 0.5) - _cdf(float(k) - 0.5) for k in support]
    total = sum(weights)
    if total <= 0.0:
        raise ValueError("degenerate EMOS weights")
    return {int(k): float(w / total) for k, w in zip(support, weights, strict=True)}


def predict_dist(
    model: FittedMosEmosLite,
    X: np.ndarray,
    support_k_per_row: Iterable[Iterable[int]],
) -> list[dict[int, float]]:
    centers = predict_latent(model, X)
    return [
        gaussian_discrete_dist(float(center), sk, sigma=model.sigma)
        for center, sk in zip(centers, support_k_per_row, strict=True)
    ]


def predict_int(model: FittedMosEmosLite, X: np.ndarray) -> np.ndarray:
    centers = predict_latent(model, X)
    return np.array([Q(float(v)) for v in centers], dtype=np.int32)


__all__ = [
    "MosEmosLiteConfig",
    "FittedMosEmosLite",
    "fit_mos_emos_lite",
    "calibrate_sigma",
    "gaussian_discrete_dist",
    "predict_latent",
    "predict_dist",
    "predict_int",
]
