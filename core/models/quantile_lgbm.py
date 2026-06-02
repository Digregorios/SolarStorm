"""Quantile LightGBM + Conformalized Quantile Regression (T-11-8, CQR).

Frozen method (``contracts/cqr_lightgbm_quantile_v0_prereg.md``, prereg_version 1.0):
per split, per CP, fit two LightGBM quantile boosters ``q_lo = q(0.10)`` and
``q_hi = q(0.90)`` on the TRAIN slice; conformalize the bounds on a DISJOINT CALIB
slice with the additive CQR conformity score ``E_i = max(q_lo(x_i) - y_i, y_i -
q_hi(x_i))`` (Romano et al. 2019); take the finite-sample ``(1-alpha)`` quantile ``E``
at rank ``ceil((n+1)(1-alpha))`` (the same convention as ``ridge_conformal``); emit the
integer interval ``[Q(q_lo - E), Q(q_hi + E)]`` with ``hi >= lo`` enforced.

The conformity score is REAL-VALUED and ``Q`` is applied ONLY to the final conformalized
bound -- the conformal correction is never eaten by an early quantization (the T-9-5
lesson: conform on the real score, round at the very end). ``E`` may be negative when
the nominal 10/90 band already over-covers, in which case CQR correctly shrinks it.

A third optional ``q(0.50)`` booster supplies a CENTER for the RPS / point guardrail
(prereg gate conditions 4-5) via the shared band-aware softmax ``latent_to_prob_dist``;
it does NOT enter the interval, which is the pure two-quantile CQR object.

Determinism: REQ-MOD-6 (seed 42, ``deterministic=True``, ``num_threads=1``, fixed
validation tail) -> byte-reproducible boosters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import lightgbm as lgb
import numpy as np

from core.contracts.quantization import Q
from core.models.loss import latent_to_prob_dist


@dataclass(frozen=True)
class QuantileLgbmConfig:
    """Knobs for the CQR quantile boosters (frozen levels; no per-split tuning)."""

    feature_columns: tuple[str, ...]
    q_lo: float = 0.10
    q_hi: float = 0.90
    coverage: float = 0.80  # target marginal coverage = 1 - alpha
    n_estimators: int = 500
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_data_in_leaf: int = 20
    feature_fraction: float = 0.9
    bagging_fraction: float = 0.9
    bagging_freq: int = 1
    seed: int = 42
    early_stopping_rounds: int = 30
    val_frac: float = 0.2
    fit_median: bool = True  # q(0.50) center for the RPS / point guardrail only
    tau: float = 0.5  # band-aware softmax temperature (matches the Ridge prob_dist)
    mode: str = "linear"


@dataclass
class FittedQuantileLgbm:
    booster_lo: lgb.Booster
    booster_hi: lgb.Booster
    booster_mid: lgb.Booster | None
    feature_columns: tuple[str, ...]
    q_lo_level: float
    q_hi_level: float
    coverage: float
    tau: float
    mode: str
    train_n: int
    best_iter_lo: int
    best_iter_hi: int
    best_iter_mid: int | None
    feature_means_for_imputation: np.ndarray


@dataclass(frozen=True)
class CqrCalibrator:
    """The additive CQR conformal correction ``E`` frozen on the CALIB slice."""

    e_correction: float
    n_calib: int
    certified: bool  # False if n was too small to certify coverage (rank clamped)
    coverage: float


def _impute_nan(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean-impute on a copy (mirrors ridge / residual_lgbm behaviour)."""
    import warnings

    out = X.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        col_means = np.nanmean(out, axis=0)
    col_means = np.where(np.isnan(col_means), 0.0, col_means)
    inds = np.where(np.isnan(out))
    out[inds] = np.take(col_means, inds[1])
    return out, col_means


def _quantile_params(alpha: float, config: QuantileLgbmConfig) -> dict:
    return {
        "objective": "quantile",
        "alpha": float(alpha),
        "metric": "quantile",
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


def _fit_one_quantile(
    X_fit: np.ndarray,
    y_fit: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    alpha: float,
    config: QuantileLgbmConfig,
) -> tuple[lgb.Booster, int]:
    """Train a single quantile booster at level ``alpha`` with early stopping."""
    train_set = lgb.Dataset(X_fit, label=y_fit)
    valid_set = lgb.Dataset(X_val, label=y_val, reference=train_set)
    booster = lgb.train(
        params=_quantile_params(alpha, config),
        train_set=train_set,
        num_boost_round=config.n_estimators,
        valid_sets=[valid_set],
        valid_names=["val"],
        callbacks=[
            lgb.early_stopping(stopping_rounds=config.early_stopping_rounds, verbose=False),
            lgb.log_evaluation(period=0),
        ],
    )
    best_iter = int(booster.best_iteration or config.n_estimators)
    return booster, best_iter


def fit_quantile_lgbm(
    X_train: np.ndarray,
    y_train_int: np.ndarray,
    *,
    config: QuantileLgbmConfig,
) -> FittedQuantileLgbm:
    """Fit the q_lo / q_hi (+ optional q_mid) quantile boosters on TRAIN."""
    n = X_train.shape[0]
    if n < 100:
        raise ValueError(f"Need >= 100 train rows; got {n}")
    if y_train_int.shape[0] != n:
        raise ValueError("y_train_int length mismatch")

    X_imp, col_means = _impute_nan(X_train)
    y = y_train_int.astype(float)

    n_val = max(50, int(round(n * config.val_frac)))
    n_fit = n - n_val
    if n_fit < 50:
        raise ValueError("Not enough rows after carving out validation tail.")
    X_fit, X_val = X_imp[:n_fit], X_imp[n_fit:]
    y_fit, y_val = y[:n_fit], y[n_fit:]

    booster_lo, best_lo = _fit_one_quantile(
        X_fit, y_fit, X_val, y_val, alpha=config.q_lo, config=config
    )
    booster_hi, best_hi = _fit_one_quantile(
        X_fit, y_fit, X_val, y_val, alpha=config.q_hi, config=config
    )
    booster_mid: lgb.Booster | None = None
    best_mid: int | None = None
    if config.fit_median:
        booster_mid, best_mid = _fit_one_quantile(
            X_fit, y_fit, X_val, y_val, alpha=0.50, config=config
        )

    return FittedQuantileLgbm(
        booster_lo=booster_lo,
        booster_hi=booster_hi,
        booster_mid=booster_mid,
        feature_columns=config.feature_columns,
        q_lo_level=config.q_lo,
        q_hi_level=config.q_hi,
        coverage=config.coverage,
        tau=config.tau,
        mode=config.mode,
        train_n=int(n),
        best_iter_lo=best_lo,
        best_iter_hi=best_hi,
        best_iter_mid=best_mid,
        feature_means_for_imputation=col_means,
    )


def _impute_with_means(model: FittedQuantileLgbm, X: np.ndarray) -> np.ndarray:
    Xc = X.copy()
    inds = np.where(np.isnan(Xc))
    if inds[0].size:
        Xc[inds] = np.take(model.feature_means_for_imputation, inds[1])
    return Xc


def predict_quantiles(model: FittedQuantileLgbm, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Decimal ``(q_lo_pred, q_hi_pred)`` from the two boosters (before conformal).

    Quantile crossing (a booster predicting ``q_lo > q_hi`` on some row) is repaired
    row-wise by sorting the pair, so the nominal band is always well-ordered before the
    conformal correction is applied.
    """
    Xc = _impute_with_means(model, X)
    q_lo = model.booster_lo.predict(Xc, num_iteration=model.best_iter_lo)
    q_hi = model.booster_hi.predict(Xc, num_iteration=model.best_iter_hi)
    q_lo = np.asarray(q_lo, dtype=float)
    q_hi = np.asarray(q_hi, dtype=float)
    lo = np.minimum(q_lo, q_hi)
    hi = np.maximum(q_lo, q_hi)
    return lo, hi


def predict_median(model: FittedQuantileLgbm, X: np.ndarray) -> np.ndarray:
    """Decimal ``q(0.50)`` center for the RPS / point guardrail."""
    if model.booster_mid is None:
        raise ValueError("median booster not fitted (config.fit_median=False)")
    Xc = _impute_with_means(model, X)
    return np.asarray(
        model.booster_mid.predict(Xc, num_iteration=model.best_iter_mid), dtype=float
    )


def _conformal_quantile(scores: np.ndarray, coverage: float) -> tuple[float, bool]:
    """Finite-sample ``coverage`` quantile of REAL-VALUED conformity scores.

    Rank ``ceil((n+1)*coverage)`` on the sorted (signed) scores; clamped to ``[1, n]``
    so a small calib set yields the widest data-supported correction rather than
    ``+inf``. ``certified`` is False when the rank had to be clamped below the requested
    coverage. Scores are NOT abs'd -- a negative ``E`` legitimately shrinks an
    over-covering nominal band.
    """
    s = np.sort(np.asarray(scores, dtype=float))
    n = s.size
    if n == 0:
        raise ValueError("cannot conformalize on empty calib scores")
    rank = int(math.ceil((n + 1) * coverage))
    certified = rank <= n
    idx = min(max(rank, 1), n) - 1
    return float(s[idx]), certified


def conformalize(
    model: FittedQuantileLgbm,
    X_calib: np.ndarray,
    y_calib_int: np.ndarray,
    *,
    coverage: float | None = None,
) -> CqrCalibrator:
    """Freeze the additive CQR correction ``E`` on a DISJOINT calib slice.

    ``E_i = max(q_lo(x_i) - y_i, y_i - q_hi(x_i))`` is the standard CQR conformity score
    (positive when ``y_i`` is outside the nominal band, negative when comfortably inside).
    ``E`` is the finite-sample ``coverage`` quantile of ``{E_i}``.
    """
    cov = float(model.coverage if coverage is None else coverage)
    y = np.asarray(y_calib_int, dtype=float)
    if X_calib.shape[0] != y.shape[0]:
        raise ValueError("X_calib and y_calib_int length mismatch")
    q_lo, q_hi = predict_quantiles(model, X_calib)
    e_scores = np.maximum(q_lo - y, y - q_hi)
    e, certified = _conformal_quantile(e_scores, cov)
    return CqrCalibrator(
        e_correction=e, n_calib=int(y.size), certified=certified, coverage=cov
    )


def predict_interval_int(
    model: FittedQuantileLgbm, cal: CqrCalibrator, X: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Emit integer IC ``[Q(q_lo - E), Q(q_hi + E)]`` with ``hi >= lo`` enforced.

    ``Q`` is applied to the conformalized REAL-VALUED bound (round at the very end).
    """
    q_lo, q_hi = predict_quantiles(model, X)
    lo_dec = q_lo - cal.e_correction
    hi_dec = q_hi + cal.e_correction
    lo_int = np.array([Q(float(v)) for v in lo_dec], dtype=np.int32)
    hi_int = np.array([Q(float(v)) for v in hi_dec], dtype=np.int32)
    hi_int = np.maximum(hi_int, lo_int)
    return lo_int, hi_int


def predict_dist(
    model: FittedQuantileLgbm,
    X: np.ndarray,
    support_k_per_row: Iterable[Iterable[int]],
) -> list[dict[int, float]]:
    """Band-aware prob_dist around the ``q(0.50)`` center (RPS / point guardrail only)."""
    centers = predict_median(model, X)
    out: list[dict[int, float]] = []
    for v, sk in zip(centers, support_k_per_row, strict=True):
        out.append(latent_to_prob_dist(float(v), list(sk), tau=model.tau, mode=model.mode))
    return out


__all__ = [
    "QuantileLgbmConfig",
    "FittedQuantileLgbm",
    "CqrCalibrator",
    "fit_quantile_lgbm",
    "predict_quantiles",
    "predict_median",
    "conformalize",
    "predict_interval_int",
    "predict_dist",
]
