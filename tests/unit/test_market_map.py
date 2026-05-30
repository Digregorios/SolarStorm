"""Unit tests for core/decision/market_map.py."""

import pytest

from core.decision.market_map import ContractRange, assert_p_yes_normalized, p_yes


# --- prob_dist fixture --------------------------------------------------------
PROB_DIST: dict[int, float] = {
    18: 0.10,
    19: 0.25,
    20: 0.40,
    21: 0.20,
    22: 0.05,
}


# --- p_yes for exact '=k' ----------------------------------------------------
def test_p_yes_exact_hit():
    c = ContractRange(k_lo=20, k_hi=20)
    assert p_yes(PROB_DIST, c) == pytest.approx(0.40)


def test_p_yes_exact_miss():
    c = ContractRange(k_lo=25, k_hi=25)
    assert p_yes(PROB_DIST, c) == pytest.approx(0.0)


# --- p_yes for '[a,b]' -------------------------------------------------------
def test_p_yes_closed_range():
    c = ContractRange(k_lo=19, k_hi=21)
    assert p_yes(PROB_DIST, c) == pytest.approx(0.85)


# --- p_yes for '>=k' (k_hi=None) ---------------------------------------------
def test_p_yes_open_upper():
    c = ContractRange(k_lo=21, k_hi=None)
    assert p_yes(PROB_DIST, c) == pytest.approx(0.25)


# --- p_yes for '<=k' (k_lo=None) ---------------------------------------------
def test_p_yes_open_lower():
    c = ContractRange(k_lo=None, k_hi=19)
    assert p_yes(PROB_DIST, c) == pytest.approx(0.35)


# --- normalization validator --------------------------------------------------
def test_normalized_partition_passes():
    partition = [
        ContractRange(k_lo=None, k_hi=19),
        ContractRange(k_lo=20, k_hi=20),
        ContractRange(k_lo=21, k_hi=None),
    ]
    # sum = 0.35 + 0.40 + 0.25 = 1.0
    assert_p_yes_normalized(PROB_DIST, partition)


def test_normalized_partition_fails_on_overlap():
    # Overlapping contracts: sum > 1 + tol
    overlap = [
        ContractRange(k_lo=None, k_hi=21),   # 0.95
        ContractRange(k_lo=19, k_hi=None),   # 0.90
    ]
    with pytest.raises(ValueError, match="exceeds"):
        assert_p_yes_normalized(PROB_DIST, overlap)


# --- ContractRange validation -------------------------------------------------
def test_contract_range_no_bounds_raises():
    with pytest.raises(ValueError):
        ContractRange(k_lo=None, k_hi=None)


def test_contract_range_inverted_raises():
    with pytest.raises(ValueError):
        ContractRange(k_lo=25, k_hi=20)
