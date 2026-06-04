"""Baseline ladder: orchestrates degraus, computes best-null-por-CP."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LadderResult:
    level: str
    name: str
    cp: str
    mae: float = 0.0
    rmse: float = 0.0
    bias: float = 0.0
    bracket_match: float = 0.0
    rps: float = 0.0
    crps: float = 0.0
    fallback_rate: float | None = None
    p50_mode_share: float = 0.0
    corr_diff: float | None = None
    n: int = 0


def evaluate_step(
    *,
    level: str,
    name: str,
    cp: str,
    pred: dict,
    truth: int,
    fallback_rate: float = 0.0,
) -> LadderResult:
    p50 = pred["p50"]
    error = p50 - truth
    return LadderResult(
        level=level, name=name, cp=cp,
        mae=abs(error),
        rmse=error**2,
        bias=error,
        bracket_match=1.0 if round(p50) == round(truth) else 0.0,
        fallback_rate=fallback_rate,
    )


def best_null_for_cp(results: dict[str, list[LadderResult]], cp: str) -> LadderResult | None:
    """Return the baseline with lowest MAE for a given CP."""
    candidates = results.get(cp, [])
    if not candidates:
        return None
    return min(candidates, key=lambda r: r.mae)
