"""Counterfactual same-temp test (design 11 phase 3, REQ-AUD-2).

Pairs forecasts that share ``k_cp`` (same observed temperature anchor) but have
different *months*, then asks: does the model's prediction discriminate between
the two regimes? We compute AUC of (predicted T_latent_dec) vs an indicator
``high-month`` (Sep..Mar, summer-half NZ) over those pairs.

Implementation note: with month as the only proxy for "regime" until Phase 4
(GMM), this is an approximation. AUC > 0.70 means the model uses information
beyond ``k_cp``.
"""

from __future__ import annotations

import numpy as np


def auc_roc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Standard ROC-AUC via Mann-Whitney U; ties get 0.5 weight."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    if s.size != y.size:
        raise ValueError("scores/labels length mismatch")
    pos = s[y == 1]
    neg = s[y == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    n_correct = 0.0
    for sp in pos:
        n_correct += float(np.sum(sp > neg)) + 0.5 * float(np.sum(sp == neg))
    return n_correct / (pos.size * neg.size)


def counterfactual_same_temp_auc(
    *,
    k_cp: np.ndarray,
    month: np.ndarray,
    pred_latent: np.ndarray,
    high_months: tuple[int, ...] = (10, 11, 12, 1, 2, 3),
) -> tuple[float, int]:
    """Restrict to (k_cp, month_class) pairs where each k_cp has both labels in
    ``high_months`` and the complement.

    Returns (AUC, n_pairs).
    """
    k = np.asarray(k_cp, dtype=int)
    m = np.asarray(month, dtype=int)
    p = np.asarray(pred_latent, dtype=float)
    label = np.isin(m, high_months).astype(int)

    # keep only k values with both classes represented
    keep_mask = np.zeros(k.size, dtype=bool)
    for kv in np.unique(k):
        rows = k == kv
        if label[rows].sum() > 0 and (1 - label[rows]).sum() > 0:
            keep_mask |= rows
    if keep_mask.sum() < 2:
        return float("nan"), 0
    return auc_roc(p[keep_mask], label[keep_mask]), int(keep_mask.sum())


__all__ = ["auc_roc", "counterfactual_same_temp_auc"]
