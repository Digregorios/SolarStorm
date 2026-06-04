import pytest
from solarstorm.data._settlement import (
    bracket_for, integer_settlement, flip_risk, FlipRisk,
)


def test_integer_settlement_standard():
    assert integer_settlement(14.4) == 14
    assert integer_settlement(14.5) == 15
    assert integer_settlement(14.6) == 15


def test_integer_settlement_negative():
    assert integer_settlement(-2.4) == -2
    assert integer_settlement(-2.5) == -2   # Python banker's rounding — but we want commercial
    assert integer_settlement(-2.6) == -3


def test_flip_risk_max_at_integer():
    r = flip_risk(15.0)
    assert r.risk == pytest.approx(0.5)
    assert r.direction == "either"


def test_flip_risk_zero_at_boundary():
    r = flip_risk(15.5)
    assert r.risk == pytest.approx(0.0)
    assert r.direction == "stable"


def test_flip_risk_inside_bucket():
    r = flip_risk(15.3)
    assert 0.15 < r.risk < 0.25
    assert r.nearest_boundary == 15.5


def test_bracket_for_maps_to_contract_bucket():
    assert bracket_for(14.2) == 14
    assert bracket_for(14.7) == 15
    assert bracket_for(0.3) == 0


def test_0_1_c_crosses_bracket_boundary():
    """The catastrophic case: 14.4→14, 14.5→15. This must be systematic (P4)."""
    assert bracket_for(14.4) == 14
    assert bracket_for(14.5) == 15
    assert bracket_for(14.4) != bracket_for(14.5)
