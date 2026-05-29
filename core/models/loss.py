"""Band-aware loss and latent->prob_dist mapping (design 8.1, 8.1.1).

The loss is zero when ``y_pred in B(k_truth)``; outside the band it grows linearly
or quadratically. ``tau`` is a frozen hyperparameter (REQ-MOD-6) read from
``nzwn/config/model.yaml``; tuning ``tau`` belongs to ``MODEL_VERSION``, NOT to
threshold tuning (REQ-MET-6).
"""

from __future__ import annotations

import math
from typing import Iterable

from core.contracts.quantization import B, distance_to_band


def band_aware_loss(
    y_pred: float,
    y_true_int: int,
    *,
    alpha: float = 1.0,
    mode: str = "linear",
) -> float:
    """Loss compatible with integer truth (REQ-MOD-2).

    - 0 if ``y_pred in B(y_true_int)``.
    - Linear: ``alpha * dist`` where ``dist`` is the distance to the band.
    - Quadratic: ``alpha * dist^2``.
    """
    dist = distance_to_band(y_pred, y_true_int)
    if dist == 0.0:
        return 0.0
    if mode == "linear":
        return alpha * dist
    if mode == "quadratic":
        return alpha * dist * dist
    raise ValueError(f"Unsupported mode '{mode}'.")


def latent_to_prob_dist(
    t_latent_dec: float,
    support_k: Iterable[int],
    *,
    tau: float,
    mode: str = "linear",
    alpha: float = 1.0,
) -> dict[int, float]:
    """Softmax band-aware over ``support_k`` (design 8.1.1).

    ``P(k) prop exp(-loss_band(t_latent_dec, k) / tau)`` normalised on ``support_k``.
    """
    if tau <= 0.0:
        raise ValueError("tau must be > 0.")
    support = list(support_k)
    if not support:
        raise ValueError("support_k must be non-empty.")
    losses = [band_aware_loss(t_latent_dec, k, alpha=alpha, mode=mode) for k in support]
    logits = [-l / tau for l in losses]
    z = max(logits)
    exps = [math.exp(v - z) for v in logits]
    s = sum(exps)
    return {k: float(e / s) for k, e in zip(support, exps, strict=True)}


__all__ = ["band_aware_loss", "latent_to_prob_dist"]
