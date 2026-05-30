"""Execution contract (REQ-MET-5, contracts/execution.md).

EXECUTION_VERSION = 1.0
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EXECUTION_VERSION = "1.0"

SlippageModel = Literal["taker_at_quote"]
EntryPriceRule = Literal["ask"]
FillRule = Literal["assume_full_fill", "partial_fill_with_min_size"]
PositionSizing = Literal["1_unit_notional", "fractional_kelly"]
TimeInForce = Literal["cancel_unfilled_at_next_cp"]


class ExecutionContract(BaseModel):
    """Frozen execution parameters for live EV + sizing (REQ-MET-5)."""

    model_config = ConfigDict(extra="forbid")

    fee_bps: int = Field(default=200, ge=0, le=1000)
    slippage_model: SlippageModel = "taker_at_quote"
    entry_price_rule: EntryPriceRule = "ask"
    fill_rule: FillRule = "assume_full_fill"
    position_sizing: PositionSizing = "1_unit_notional"
    max_concurrent_positions: int = Field(default=1, ge=1)
    time_in_force: TimeInForce = "cancel_unfilled_at_next_cp"
    min_fill_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    # Live fractional-Kelly cap (only used when position_sizing == 'fractional_kelly').
    kelly_cap: float = Field(default=0.25, ge=0.0, le=1.0)


def default_execution_contract() -> ExecutionContract:
    """Return the frozen v1.0 default contract."""
    return ExecutionContract()


__all__ = [
    "EXECUTION_VERSION",
    "ExecutionContract",
    "default_execution_contract",
]
