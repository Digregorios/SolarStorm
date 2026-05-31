"""Live EV + Kelly sizing (REQ-MET-5; odds are live-only context, no historical backtest)."""

from __future__ import annotations

import pytest

from core.contracts.execution import ExecutionContract
from core.decision.sizing import expected_value, kelly_fraction, size_side


def test_ev_positive_edge_and_fee_drag():
    # p=0.70, price=0.50, fee_bps=0 -> EV = 0.20
    assert expected_value(0.70, 0.50, fee_bps=0) == pytest.approx(0.20)
    # fee drags EV down by 2*price*fee_bps/1e4
    assert expected_value(0.70, 0.50, fee_bps=200) == pytest.approx(0.20 - 2 * 0.50 * 0.02)


def test_ev_negative_when_overpriced():
    assert expected_value(0.40, 0.60, fee_bps=0) == pytest.approx(-0.20)


def test_kelly_zero_on_nonpositive_edge():
    assert kelly_fraction(0.50, 0.50) == 0.0   # fair price -> no edge
    assert kelly_fraction(0.30, 0.60) == 0.0   # negative edge


def test_kelly_positive_and_capped():
    # p=0.70, price=0.50 -> b=1, f*=(0.7*1-0.3)/1=0.40; cap 0.25 -> 0.10
    assert kelly_fraction(0.70, 0.50, kelly_cap=0.25) == pytest.approx(0.40 * 0.25)
    # cap 1.0 returns full Kelly
    assert kelly_fraction(0.70, 0.50, kelly_cap=1.0) == pytest.approx(0.40)


def test_kelly_monotonic_in_edge():
    a = kelly_fraction(0.60, 0.50, kelly_cap=1.0)
    b = kelly_fraction(0.80, 0.50, kelly_cap=1.0)
    assert b > a > 0.0


def test_size_side_buy_no_uses_complement():
    # p_yes=0.30 -> BUY_NO win-prob 0.70 at no-price 0.50: positive edge.
    r = size_side("BUY_NO", p_yes=0.30, price=0.50)
    assert r.p_model == pytest.approx(0.70)
    assert r.expected_value > 0.0


def test_size_side_buy_no_semantics_from_decision_line():
    # Reviewer-specified case: contract p_yes=0.026, BUY_NO at no-price 0.605.
    # size_side takes p_yes and must convert to win-prob 1-0.026=0.974; EV strongly positive.
    r = size_side("BUY_NO", p_yes=0.026, price=0.605, contract=ExecutionContract(fee_bps=0))
    assert r.p_model == pytest.approx(0.974)
    assert r.expected_value == pytest.approx(0.974 - 0.605)  # = 0.369


def test_size_side_flat_default_takes_one_unit_on_positive_edge_only():
    pos = size_side("BUY_YES", p_yes=0.70, price=0.50)  # default 1_unit_notional
    assert pos.stake == 1.0
    neg = size_side("BUY_YES", p_yes=0.40, price=0.60)
    assert neg.stake == 0.0


def test_size_side_kelly_contract_uses_kelly_stake():
    cfg = ExecutionContract(position_sizing="fractional_kelly", kelly_cap=0.25, fee_bps=0)
    r = size_side("BUY_YES", p_yes=0.70, price=0.50, contract=cfg)
    assert r.stake == pytest.approx(r.kelly_fraction) and r.stake > 0.0


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        expected_value(1.2, 0.5)
    with pytest.raises(ValueError):
        kelly_fraction(0.5, 0.0)
    with pytest.raises(ValueError):
        size_side("HOLD", 0.5, 0.5)


def test_size_book_picks_positive_ev_brackets():
    from dataclasses import dataclass

    from core.decision.market_map import ContractRange
    from core.decision.sizing import size_book

    @dataclass(frozen=True)
    class _B:
        contract: ContractRange
        label: str
        price_yes: float
        price_no: float

    # Model concentrates mass on 18; market underprices YES@18 (0.30) -> positive YES edge.
    pd_ = {17: 0.10, 18: 0.70, 19: 0.20}
    brackets = [
        _B(ContractRange(18, 18), "18C", price_yes=0.30, price_no=0.70),   # YES edge +0.40 pre-fee
        _B(ContractRange(17, 17), "17C", price_yes=0.50, price_no=0.50),   # YES neg, NO edge ~ -0.10
    ]
    book = size_book(pd_, brackets, contract=ExecutionContract(fee_bps=0))
    assert book and book[0][0] == "18C" and book[0][1].side == "BUY_YES"
    assert book[0][1].expected_value > 0.0

