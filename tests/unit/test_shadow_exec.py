"""Unit tests for core/decision/shadow_exec.py."""

import pytest

from core.contracts.execution import ExecutionContract
from core.decision.market_map import ContractRange
from core.decision.shadow_exec import (
    Decision,
    MarketSnapshot,
    TradeResult,
    shadow_simulate,
)


def _market(price_yes: float = 0.60, price_no: float = 0.40) -> MarketSnapshot:
    return MarketSnapshot(
        contract=ContractRange(k_lo=20, k_hi=20),
        price_yes=price_yes,
        price_no=price_no,
    )


def _exec(**kw) -> ExecutionContract:
    return ExecutionContract(**kw)


# --- NO_TRADE -> pnl 0 -------------------------------------------------------
def test_no_trade_pnl_zero():
    d = Decision(side="NO_TRADE", contract=ContractRange(k_lo=20, k_hi=20))
    r = shadow_simulate(d, _market(), _exec(), truth=20)
    assert r.pnl == 0.0
    assert r.filled is False
    assert r.fee_paid == 0.0


# --- BUY_YES resolved in favor -----------------------------------------------
def test_buy_yes_win():
    d = Decision(side="BUY_YES", contract=ContractRange(k_lo=20, k_hi=20))
    r = shadow_simulate(d, _market(price_yes=0.60), _exec(fee_bps=200), truth=20)
    # payoff=1.0, entry=0.60, fee_per_side=0.60*200/10000=0.012
    # pnl = (1.0 - 0.60) - 2*0.012 = 0.376
    assert r.filled is True
    assert r.pnl == pytest.approx(0.376)
    assert r.fee_paid == pytest.approx(0.024)
    assert r.entry_price == pytest.approx(0.60)
    assert r.payoff == 1.0


# --- BUY_YES resolved against ------------------------------------------------
def test_buy_yes_lose():
    d = Decision(side="BUY_YES", contract=ContractRange(k_lo=20, k_hi=20))
    r = shadow_simulate(d, _market(price_yes=0.60), _exec(fee_bps=200), truth=19)
    # payoff=0.0, pnl = (0.0 - 0.60) - 0.024 = -0.624
    assert r.filled is True
    assert r.pnl == pytest.approx(-0.624)
    assert r.payoff == 0.0


# --- BUY_NO resolved in favor ------------------------------------------------
def test_buy_no_win():
    d = Decision(side="BUY_NO", contract=ContractRange(k_lo=20, k_hi=20))
    r = shadow_simulate(d, _market(price_no=0.40), _exec(fee_bps=200), truth=19)
    # truth=19 not in [20,20] -> resolved in favor of NO
    # entry=0.40, fee=0.40*200/10000=0.008
    # pnl = (1.0 - 0.40) - 2*0.008 = 0.584
    assert r.filled is True
    assert r.pnl == pytest.approx(0.584)
    assert r.fee_paid == pytest.approx(0.016)


# --- BUY_NO resolved against -------------------------------------------------
def test_buy_no_lose():
    d = Decision(side="BUY_NO", contract=ContractRange(k_lo=20, k_hi=20))
    r = shadow_simulate(d, _market(price_no=0.40), _exec(fee_bps=200), truth=20)
    # truth=20 in [20,20] -> resolved AGAINST NO
    # pnl = (0.0 - 0.40) - 0.016 = -0.416
    assert r.filled is True
    assert r.pnl == pytest.approx(-0.416)


# --- Fee charged both sides ---------------------------------------------------
def test_fee_both_sides():
    d = Decision(side="BUY_YES", contract=ContractRange(k_lo=20, k_hi=20))
    r = shadow_simulate(d, _market(price_yes=0.50), _exec(fee_bps=100), truth=20)
    # fee_per_side = 0.50 * 100 / 10000 = 0.005
    assert r.fee_paid == pytest.approx(0.010)


# --- partial_fill_with_min_size: min_fill_fraction=0 -> no fill ---------------
def test_partial_fill_no_fill():
    d = Decision(side="BUY_YES", contract=ContractRange(k_lo=20, k_hi=20))
    ec = _exec(fill_rule="partial_fill_with_min_size", min_fill_fraction=0.0)
    r = shadow_simulate(d, _market(), ec, truth=20)
    assert r.filled is False
    assert r.pnl == 0.0


# --- open range contracts -----------------------------------------------------
def test_buy_yes_open_upper_win():
    c = ContractRange(k_lo=20, k_hi=None)
    d = Decision(side="BUY_YES", contract=c)
    m = MarketSnapshot(contract=c, price_yes=0.50, price_no=0.50)
    r = shadow_simulate(d, m, _exec(fee_bps=0), truth=22)
    assert r.pnl == pytest.approx(0.50)  # (1-0.5) - 0


def test_buy_yes_open_lower_win():
    c = ContractRange(k_lo=None, k_hi=19)
    d = Decision(side="BUY_YES", contract=c)
    m = MarketSnapshot(contract=c, price_yes=0.30, price_no=0.70)
    r = shadow_simulate(d, m, _exec(fee_bps=0), truth=18)
    assert r.pnl == pytest.approx(0.70)  # (1-0.3) - 0


# --- determinism --------------------------------------------------------------
def test_deterministic():
    d = Decision(side="BUY_YES", contract=ContractRange(k_lo=20, k_hi=20))
    m = _market()
    ec = _exec()
    r1 = shadow_simulate(d, m, ec, truth=20)
    r2 = shadow_simulate(d, m, ec, truth=20)
    assert r1 == r2
