"""Unit tests for core/contracts/execution.py."""

import pytest
from pydantic import ValidationError

from core.contracts.execution import (
    EXECUTION_VERSION,
    ExecutionContract,
    default_execution_contract,
)


def test_version_constant():
    assert EXECUTION_VERSION == "1.0"


def test_default_contract_values():
    c = default_execution_contract()
    assert c.fee_bps == 200
    assert c.slippage_model == "taker_at_quote"
    assert c.entry_price_rule == "ask"
    assert c.fill_rule == "assume_full_fill"
    assert c.position_sizing == "1_unit_notional"
    assert c.max_concurrent_positions == 1
    assert c.time_in_force == "cancel_unfilled_at_next_cp"
    assert c.min_fill_fraction == 0.0


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        ExecutionContract(bogus=42)


def test_fee_bps_out_of_range():
    with pytest.raises(ValidationError):
        ExecutionContract(fee_bps=2000)
    with pytest.raises(ValidationError):
        ExecutionContract(fee_bps=-1)


def test_invalid_fill_rule():
    with pytest.raises(ValidationError):
        ExecutionContract(fill_rule="magic")


def test_frozen_roundtrip():
    c = default_execution_contract()
    c2 = ExecutionContract.model_validate(c.model_dump())
    assert c == c2
