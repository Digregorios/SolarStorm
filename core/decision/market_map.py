"""Market mapping: prob_dist -> p_yes for contract ranges (design section 10).

Supports contract types:
  '=k'    exact integer
  '[a,b]' closed range
  '>=k'   open upper (k_hi=None)
  '<=k'   open lower (k_lo=None)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ContractRange:
    """A single Polymarket contract range."""

    k_lo: Optional[int] = None
    k_hi: Optional[int] = None

    def __post_init__(self) -> None:
        if self.k_lo is None and self.k_hi is None:
            raise ValueError("ContractRange must have at least one bound.")
        if self.k_lo is not None and self.k_hi is not None and self.k_lo > self.k_hi:
            raise ValueError(f"k_lo={self.k_lo} > k_hi={self.k_hi}")


def p_yes(prob_dist: dict[int, float], contract: ContractRange) -> float:
    """Sum prob_dist[k] for k in support where k_lo <= k <= k_hi."""
    total = 0.0
    for k, p in prob_dist.items():
        if contract.k_lo is not None and k < contract.k_lo:
            continue
        if contract.k_hi is not None and k > contract.k_hi:
            continue
        total += p
    return total


def assert_p_yes_normalized(
    prob_dist: dict[int, float],
    contracts: list[ContractRange],
    tol: float = 0.02,
) -> None:
    """Raise if sum of p_yes over a partition exceeds 1 + tol."""
    total = sum(p_yes(prob_dist, c) for c in contracts)
    if total > 1.0 + tol:
        raise ValueError(
            f"Partition p_yes sum={total:.4f} exceeds 1 + {tol}."
        )


__all__ = [
    "ContractRange",
    "p_yes",
    "assert_p_yes_normalized",
]
