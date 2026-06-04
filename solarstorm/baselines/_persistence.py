"""L0+L1 baselines: persistence (t_so_far), dminus1 (yesterday's Tmax)."""
from __future__ import annotations


def predict_persistence(*, k_cp: int) -> dict:
    """L0: Tmax = temperature right now at the checkpoint."""
    return {
        "p50": k_cp,
        "source": "persistence",
        "prob_dist": {k_cp: 1.0},
    }


def predict_dminus1(*, tmax_dminus1: int) -> dict:
    """L1: Tmax = yesterday's maximum."""
    return {
        "p50": tmax_dminus1,
        "source": "dminus1",
        "prob_dist": {tmax_dminus1: 1.0},
    }
