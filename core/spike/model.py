"""Late-spike binary classifier (REQ-SPK-2/3, REQ-MOD-6, design section 9).

LightGBM binary + IsotonicRegression calibration -> spike_risk in [0, 1].
Deterministic: fixed seeds throughout.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
from sklearn.isotonic import IsotonicRegression


@dataclass(frozen=True)
class SpikeModelConfig:
    n_estimators: int = 300
    learning_rate: float = 0.05
    num_leaves: int = 15
    min_data_in_leaf: int = 20
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    bagging_freq: int = 1
    early_stopping_rounds: int = 30
    seed: int = 42
    val_frac: float = 0.2


@dataclass
class FittedSpikeModel:
    booster: lgb.Booster
    isotonic: IsotonicRegression
    best_iteration: int
    feature_means: np.ndarray
    config: SpikeModelConfig


def _impute_nan(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean-impute NaN on a copy."""
    import warnings

    out = X.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        col_means = np.nanmean(out, axis=0)
    col_means = np.where(np.isnan(col_means), 0.0, col_means)
    inds = np.where(np.isnan(out))
    out[inds] = np.take(col_means, inds[1])
    return out, col_means


def fit_spike_model(
    X: np.ndarray,
    y: np.ndarray,
    *,
    config: SpikeModelConfig | None = None,
) -> FittedSpikeModel:
    """Fit LightGBM binary + isotonic calibration.

    ``y`` is binary (0/1) for late_spike_l1.
    """
    cfg = config or SpikeModelConfig()
    n = X.shape[0]
    if n < 60:
        raise ValueError(f"Need >= 60 train rows; got {n}")

    X_imp, col_means = _impute_nan(X)
    y_arr = np.asarray(y, dtype=float)

    n_val = max(30, int(round(n * cfg.val_frac)))
    n_fit = n - n_val

    X_fit, X_val = X_imp[:n_fit], X_imp[n_fit:]
    y_fit, y_val = y_arr[:n_fit], y_arr[n_fit:]

    train_set = lgb.Dataset(X_fit, label=y_fit)
    valid_set = lgb.Dataset(X_val, label=y_val, reference=train_set)

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": cfg.learning_rate,
        "num_leaves": cfg.num_leaves,
        "min_data_in_leaf": cfg.min_data_in_leaf,
        "feature_fraction": cfg.feature_fraction,
        "bagging_fraction": cfg.bagging_fraction,
        "bagging_freq": cfg.bagging_freq,
        "verbose": -1,
        "seed": cfg.seed,
        "bagging_seed": cfg.seed,
        "feature_fraction_seed": cfg.seed,
        "drop_seed": cfg.seed,
        "deterministic": True,
        "force_col_wise": True,
        "num_threads": 1,
    }

    booster = lgb.train(
        params=params,
        train_set=train_set,
        num_boost_round=cfg.n_estimators,
        valid_sets=[valid_set],
        valid_names=["val"],
        callbacks=[
            lgb.early_stopping(stopping_rounds=cfg.early_stopping_rounds, verbose=False),
            lgb.log_evaluation(period=0),
        ],
    )
    best_iter = int(booster.best_iteration or cfg.n_estimators)

    # Isotonic calibration on validation fold raw probabilities
    raw_val = booster.predict(X_val, num_iteration=best_iter)
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(raw_val, y_val)

    return FittedSpikeModel(
        booster=booster,
        isotonic=iso,
        best_iteration=best_iter,
        feature_means=col_means,
        config=cfg,
    )


def predict_spike_risk(model: FittedSpikeModel, X: np.ndarray) -> np.ndarray:
    """Return calibrated spike_risk in [0, 1]."""
    Xc = X.copy()
    inds = np.where(np.isnan(Xc))
    if inds[0].size:
        Xc[inds] = np.take(model.feature_means, inds[1])
    raw = model.booster.predict(Xc, num_iteration=model.best_iteration)
    calibrated = model.isotonic.transform(raw)
    return np.clip(calibrated, 0.0, 1.0)


__all__ = [
    "SpikeModelConfig",
    "FittedSpikeModel",
    "fit_spike_model",
    "predict_spike_risk",
]
