"""Shadow execution simulator (design 10.1, REQ-MET-5).

Deterministic for same inputs. Decoupled from engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from core.contracts.execution import ExecutionContract
from core.decision.market_map import ContractRange


Side = Literal["BUY_YES", "BUY_NO", "NO_TRADE"]


@dataclass(frozen=True)
class MarketSnapshot:
    """Quoted prices for a single contract at a checkpoint."""

    contract: ContractRange
    price_yes: float
    price_no: float


@dataclass(frozen=True)
class Decision:
    """Minimal decision input for the simulator."""

    side: Side
    contract: ContractRange


@dataclass(frozen=True)
class TradeResult:
    """Output of shadow_simulate."""

    pnl: float
    filled: bool
    fee_paid: float
    entry_price: float
    payoff: Optional[float] = None


def _entry_price(market: MarketSnapshot, side: Side) -> float:
    """Taker-at-quote: BUY_YES pays price_yes, BUY_NO pays price_no."""
    if side == "BUY_YES":
        return market.price_yes
    return market.price_no


def _resolved_in_favor(side: Side, contract: ContractRange, truth: int) -> bool:
    """Check if the market resolved in favor of the position."""
    k_in_range = (
        (contract.k_lo is None or truth >= contract.k_lo)
        and (contract.k_hi is None or truth <= contract.k_hi)
    )
    if side == "BUY_YES":
        return k_in_range
    return not k_in_range


def shadow_simulate(
    decision: Decision,
    market: MarketSnapshot,
    exec_contract: ExecutionContract,
    truth: int,
) -> TradeResult:
    """Simulate a single trade under the execution contract.

    Args:
        decision: side + contract range.
        market: quoted prices.
        exec_contract: frozen execution params.
        truth: realized Tmax integer (y_true_int).

    Returns:
        TradeResult with pnl, filled, fee_paid, entry_price.
    """
    no_fill = TradeResult(pnl=0.0, filled=False, fee_paid=0.0, entry_price=0.0)

    if decision.side == "NO_TRADE":
        return no_fill

    entry = _entry_price(market, decision.side)

    # Fill logic
    if exec_contract.fill_rule == "partial_fill_with_min_size":
        if exec_contract.min_fill_fraction <= 0.0:
            return no_fill
    # assume_full_fill: always filled

    fee = entry * exec_contract.fee_bps / 1e4
    payoff = 1.0 if _resolved_in_favor(decision.side, decision.contract, truth) else 0.0
    pnl = (payoff - entry) - 2.0 * fee  # notional = 1 unit

    return TradeResult(
        pnl=pnl,
        filled=True,
        fee_paid=2.0 * fee,
        entry_price=entry,
        payoff=payoff,
    )


__all__ = [
    "Side",
    "MarketSnapshot",
    "Decision",
    "TradeResult",
    "shadow_simulate",
]
