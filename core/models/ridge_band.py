"""Ridge band-aware model (Phase 3, design 8).

The model predicts a *delta* relative to a climatology baseline when one is
provided; otherwise it predicts the integer temperature directly. Either way
the output is ``T_latent_dec`` (decimal degC), passed through softmax
band-aware (design 8.1.1) to produce the final ``prob_dist``.

Hyperparameter selection: grid search over Ridge alpha, scored by mean
``band_aware_loss(T_latent_dec, target_tmax_int)`` on a held-out validation slice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from sklearn.linear_model import Ridge

from core.contracts.quantization import Q
from core.models.loss import band_aware_loss, latent_to_prob_dist


@dataclass(frozen=True)
class RidgeBandConfig:
    feature_columns: tuple[str, ...]
    alphas: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0)
    tau: float = 0.5
    mode: str = "linear"
    seed: int = 42
    use_climatology_anchor: bool = True


@dataclass
class FittedRidgeBand:
    ridge: Ridge
    feature_columns: tuple[str, ...]
    feature_means: np.ndarray
    feature_stds: np.ndarray
    alpha: float
    tau: float
    mode: str
    train_n: int
    use_climatology_anchor: bool


def _impute_nan(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean-impute NaN values in a copy of ``X``.

    Returns ``(X_imputed_copy, col_means)``. The input is *never* mutated
    (review-v2 #N4: the previous version mutated in place AND returned the
    array, which silently corrupted callers that passed a slice/view).
    All-NaN columns fall back to ``0.0`` (RuntimeWarning suppressed).
    """
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


def fit_ridge_band(
    X_train: np.ndarray,
    y_train_int: np.ndarray,
    *,
    config: RidgeBandConfig,
    clim_train: np.ndarray | None = None,
    val_frac: float = 0.2,
) -> FittedRidgeBand:
    """Fit Ridge; alpha picked by band-aware loss on the chronological val tail.

    If ``config.use_climatology_anchor`` and ``clim_train`` is provided, the
    Ridge fits on ``y_train_int - clim_train`` and the prediction at scoring
    time is reconstructed as ``ridge.predict(X) + clim``. Otherwise it fits on
    ``y_train_int`` directly.

    ``val_frac`` (review-v2 #N1) is an *internal chronological* split used to
    score Ridge ``alpha`` on the most recent rows of the supplied ``X_train``.
    It is **not** a cross-validation parameter - the outer walk-forward CV
    (``core/eval/cv.py``) is unrelated and operates on a different time scale.
    Reducing ``val_frac`` to zero would defeat alpha selection and is
    intentionally not supported (the function will raise via the ``n_fit < 50``
    guard). Tuning ``val_frac`` for performance is *forbidden* by REQ-MET-6
    (only operational thresholds may be tuned).
    """
    n = X_train.shape[0]
    if n < 100:
        raise ValueError(f"Need >= 100 train rows; got {n}")
    if config.use_climatology_anchor and clim_train is None:
        raise ValueError("use_climatology_anchor=True requires clim_train")
    if config.use_climatology_anchor:
        clim = np.asarray(clim_train, dtype=float)
        if clim.size != n:
            raise ValueError("clim_train length must match X_train rows")
        y_target = y_train_int.astype(float) - clim
    else:
        clim = np.zeros(n)
        y_target = y_train_int.astype(float)

    n_val = max(50, int(round(n * val_frac)))
    n_fit = n - n_val
    if n_fit < 50:
        raise ValueError("Not enough rows after carving out validation tail.")

    X_fit = X_train[:n_fit].copy()
    X_val = X_train[n_fit:].copy()
    clim_val = clim[n_fit:]
    y_fit = y_target[:n_fit]
    y_val_int = y_train_int[n_fit:]

    X_fit, col_means = _impute_nan(X_fit)
    mean = X_fit.mean(axis=0)
    std = X_fit.std(axis=0)
    X_fit_std = _standardise(X_fit, mean, std)
    inds = np.where(np.isnan(X_val))
    X_val[inds] = np.take(col_means, inds[1])
    X_val_std = _standardise(X_val, mean, std)

    best_alpha = config.alphas[0]
    best_loss = math.inf
    for alpha in config.alphas:
        ridge = Ridge(alpha=alpha, random_state=config.seed)
        ridge.fit(X_fit_std, y_fit)
        pred = ridge.predict(X_val_std)
        t_latent = pred + clim_val if config.use_climatology_anchor else pred
        loss = float(
            np.mean([
                band_aware_loss(float(p), int(t), alpha=1.0, mode=config.mode)
                for p, t in zip(t_latent, y_val_int)
            ])
        )
        if loss < best_loss:
            best_loss = loss
            best_alpha = alpha

    # Refit on FULL train at the chosen alpha
    X_full = X_train.copy()
    X_full, _ = _impute_nan(X_full)
    mean_full = X_full.mean(axis=0)
    std_full = X_full.std(axis=0)
    X_full_std = _standardise(X_full, mean_full, std_full)
    ridge = Ridge(alpha=best_alpha, random_state=config.seed)
    ridge.fit(X_full_std, y_target)
    return FittedRidgeBand(
        ridge=ridge,
        feature_columns=config.feature_columns,
        feature_means=mean_full,
        feature_stds=std_full,
        alpha=best_alpha,
        tau=config.tau,
        mode=config.mode,
        train_n=int(n),
        use_climatology_anchor=config.use_climatology_anchor,
    )


def predict_latent(
    model: FittedRidgeBand,
    X: np.ndarray,
    clim: np.ndarray | None = None,
) -> np.ndarray:
    """Predict T_latent_dec for each row.

    When ``model.use_climatology_anchor`` is True, ``clim`` (one value per row)
    is mandatory and added back to the Ridge raw output.
    """
    if model.use_climatology_anchor and clim is None:
        raise ValueError("predict_latent requires clim when use_climatology_anchor=True")
    Xc = X.copy()
    inds = np.where(np.isnan(Xc))
    if inds[0].size:
        Xc[inds] = np.take(model.feature_means, inds[1])
    Xstd = _standardise(Xc, model.feature_means, model.feature_stds)
    pred = model.ridge.predict(Xstd)
    if model.use_climatology_anchor:
        return pred + np.asarray(clim, dtype=float)
    return pred


def predict_dist(
    model: FittedRidgeBand,
    X: np.ndarray,
    support_k_per_row: Iterable[Iterable[int]],
    clim: np.ndarray | None = None,
) -> list[dict[int, float]]:
    latents = predict_latent(model, X, clim=clim)
    out: list[dict[int, float]] = []
    for t_latent, sk in zip(latents, support_k_per_row, strict=True):
        out.append(
            latent_to_prob_dist(float(t_latent), list(sk), tau=model.tau, mode=model.mode)
        )
    return out


def predict_int(
    model: FittedRidgeBand, X: np.ndarray, clim: np.ndarray | None = None
) -> np.ndarray:
    latents = predict_latent(model, X, clim=clim)
    return np.array([Q(float(v)) for v in latents], dtype=np.int32)


__all__ = [
    "RidgeBandConfig",
    "FittedRidgeBand",
    "fit_ridge_band",
    "predict_latent",
    "predict_dist",
    "predict_int",
]
