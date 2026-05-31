"""analog_high_risk_arm_v0 (T-9-1): analog-based point forecast correction.

Blends an analog estimate into Ridge ONLY on ex-ante non-calm days (predicted
late-warming risk >= c30). Frozen constants; no per-split tuning.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import polars as pl

from core.contracts.quantization import Q
from core.models.late_warming_risk import (
    FEATURE_NAMES,
    build_features,
    fit_risk_model,
    predict_risk,
)

# Frozen constants (prereg v1.0)
W_MAX = 0.5
CONF_REF = 0.20
K_NEIGHBORS = 50
LAPLACE_ALPHA = 1
SEED = 42

# 7-feature causal distance vector
ANALOG_FEATURES = (
    "k_cp",
    "delta_06_to_cp",
    "southerly_at_cp",
    "rain_persistence_path",
    "s_to_n",
    "month_sin",
    "month_cos",
)


@dataclass
class AnalogArmState:
    """Per-split fitted state for the analog arm."""
    risk_model: object  # LateWarmingRiskModel
    c30: float
    base_rate_train: float
    pool_features: np.ndarray  # (N_train, 7)
    pool_tmax_int: np.ndarray
    pool_k_cp: np.ndarray
    pool_target: np.ndarray  # binary late-warming indicator
    feat_mean: np.ndarray
    feat_std: np.ndarray


def _extract_analog_matrix(df: pl.DataFrame) -> np.ndarray:
    """Extract the 7 analog features as a float matrix."""
    cols = []
    for c in ANALOG_FEATURES:
        v = df[c].to_numpy().astype(float)
        cols.append(np.where(np.isnan(v), 0.0, v))
    return np.column_stack(cols)


def fit_analog_arm(
    risk_df: pl.DataFrame,
    *,
    calib_df: pl.DataFrame | None = None,
    seed: int = SEED,
) -> AnalogArmState:
    """Fit the analog arm state on a TRAIN risk_df (output of build_features).

    risk_df must have columns: ANALOG_FEATURES + target + tmax_int (from labels).
    calib_df is the held-out 120d slice for isotonic calibration of the risk model.
    """
    # Fit the logistic risk model
    risk_model = fit_risk_model(risk_df, calib=calib_df, seed=seed)

    # Compute c30 = 30th percentile of train predicted risk
    train_risk = predict_risk(risk_model, risk_df)
    c30 = float(np.percentile(train_risk, 30))

    # Base rate of late-warming in train
    targets = risk_df["target"].to_numpy().astype(float)
    base_rate_train = float(np.mean(targets))

    # Pool features (standardized with train-only stats)
    pool_raw = _extract_analog_matrix(risk_df)
    feat_mean = pool_raw.mean(axis=0)
    feat_std = pool_raw.std(axis=0)
    feat_std = np.where(feat_std < 1e-9, 1.0, feat_std)
    pool_features = (pool_raw - feat_mean) / feat_std

    # Pool labels
    pool_tmax_int = risk_df["tmax_int"].to_numpy().astype(float)
    pool_k_cp = risk_df["k_cp"].to_numpy().astype(float)
    pool_target = targets

    return AnalogArmState(
        risk_model=risk_model,
        c30=c30,
        base_rate_train=base_rate_train,
        pool_features=pool_features,
        pool_tmax_int=pool_tmax_int,
        pool_k_cp=pool_k_cp,
        pool_target=pool_target,
        feat_mean=feat_mean,
        feat_std=feat_std,
    )


def predict_analog(
    state: AnalogArmState,
    test_row: dict,
    ridge_pred: int,
) -> int:
    """Produce the blended prediction for a single test day.

    test_row must have keys: ANALOG_FEATURES + the risk model features.
    Returns the final integer prediction (blend or ridge passthrough).
    """
    # Ex-ante gate: predict risk for this day
    # Build a 1-row df for predict_risk
    risk_row = {fn: test_row.get(fn) for fn in FEATURE_NAMES}
    risk_df = pl.DataFrame([risk_row])
    p_risk = predict_risk(state.risk_model, risk_df)[0]

    if p_risk < state.c30:
        # Calm day -> passthrough Ridge
        return ridge_pred

    # Retrieve K nearest neighbors from pool
    raw = np.array([float(test_row.get(f) or 0.0) for f in ANALOG_FEATURES])
    query = (raw - state.feat_mean) / state.feat_std

    dists = np.linalg.norm(state.pool_features - query, axis=1)
    k = min(K_NEIGHBORS, len(dists))
    idx = np.argpartition(dists, k)[:k]

    # Analog delta (Laplace-smoothed mean)
    neighbor_deltas = state.pool_tmax_int[idx] - state.pool_k_cp[idx]
    analog_delta = (neighbor_deltas.sum() + LAPLACE_ALPHA * 0.0) / (k + LAPLACE_ALPHA)

    # Analog pred
    k_cp_test = float(test_row.get("k_cp") or 0.0)
    analog_pred = k_cp_test + analog_delta

    # P_analog = smoothed neighbor late-warming frequency
    n_lw = state.pool_target[idx].sum()
    p_analog = (n_lw + LAPLACE_ALPHA * state.base_rate_train) / (k + LAPLACE_ALPHA)

    # Confidence
    analog_conf = abs(p_analog - state.base_rate_train)

    # Blend weight
    w = W_MAX * min(max(analog_conf / CONF_REF, 0.0), 1.0)

    # Blend
    blend = (1.0 - w) * float(ridge_pred) + w * analog_pred
    return Q(blend)


def predict_analog_batch(
    state: AnalogArmState,
    test_df: pl.DataFrame,
    ridge_preds: np.ndarray,
) -> np.ndarray:
    """Batch prediction for all test rows. Returns int array of blended preds."""
    n = test_df.height
    out = np.empty(n, dtype=np.int32)
    # Pre-compute risk for all test rows at once
    risk_probs = predict_risk(state.risk_model, test_df)

    # Pre-extract test analog features
    test_raw = _extract_analog_matrix(test_df)
    test_std = (test_raw - state.feat_mean) / state.feat_std

    for i in range(n):
        if risk_probs[i] < state.c30:
            out[i] = int(ridge_preds[i])
            continue

        query = test_std[i]
        dists = np.linalg.norm(state.pool_features - query, axis=1)
        k = min(K_NEIGHBORS, len(dists))
        idx = np.argpartition(dists, k)[:k]

        neighbor_deltas = state.pool_tmax_int[idx] - state.pool_k_cp[idx]
        analog_delta = neighbor_deltas.sum() / (k + LAPLACE_ALPHA)

        k_cp_test = float(test_df["k_cp"][i])
        analog_pred = k_cp_test + analog_delta

        n_lw = state.pool_target[idx].sum()
        p_analog = (n_lw + LAPLACE_ALPHA * state.base_rate_train) / (k + LAPLACE_ALPHA)
        analog_conf = abs(p_analog - state.base_rate_train)

        w = W_MAX * min(max(analog_conf / CONF_REF, 0.0), 1.0)
        blend = (1.0 - w) * float(ridge_preds[i]) + w * analog_pred
        out[i] = Q(blend)

    return out


__all__ = [
    "ANALOG_FEATURES",
    "W_MAX",
    "CONF_REF",
    "K_NEIGHBORS",
    "LAPLACE_ALPHA",
    "AnalogArmState",
    "fit_analog_arm",
    "predict_analog",
    "predict_analog_batch",
]
