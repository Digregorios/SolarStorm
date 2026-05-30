"""Full decision engine states (T-8-3, design 10) + spike_risk->confidence wiring (T-7-5)."""

from __future__ import annotations

import numpy as np

from core.confidence.score import PHI_NAMES, confidence_score, fit_confidence
from core.decision.engine import (
    BLOCK_BUY_NO_LATE_SPIKE,
    BUY_NO,
    NO_TRADE,
    NO_TRADE_RESOLVED,
    OPPORTUNITY_ASSYMETRIC,
    REASON_LOW_CONFIDENCE,
    REASON_NO_EDGE,
    ForecastRow,
    Thresholds,
    decide,
)
from core.decision.market_map import ContractRange

# A peaked distribution on bracket 18; contract ">=18" -> p_yes high.
_PD = {16: 0.05, 17: 0.10, 18: 0.55, 19: 0.20, 20: 0.10}
_C = ContractRange(k_lo=18, k_hi=None)
_TH = Thresholds(min_confidence=0.55, spike_block=0.30, no_too_expensive=0.95,
                 min_edge_yes=0.05, min_edge_no=0.05)


def test_low_confidence_stays_out():
    f = ForecastRow(prob_dist=_PD, confidence_score=0.10, spike_risk=0.0)
    d = decide(f, _C, price_yes=0.50, price_no=0.50, thresholds=_TH)
    assert d.state == NO_TRADE and d.reason == REASON_LOW_CONFIDENCE


def test_late_spike_blocks_buy_no():
    f = ForecastRow(prob_dist=_PD, confidence_score=0.90, spike_risk=0.40)  # >= spike_block
    d = decide(f, _C, price_yes=0.50, price_no=0.50, thresholds=_TH)
    assert d.state == BLOCK_BUY_NO_LATE_SPIKE


def test_no_too_expensive_is_resolved():
    f = ForecastRow(prob_dist=_PD, confidence_score=0.90, spike_risk=0.0)
    d = decide(f, _C, price_yes=0.50, price_no=0.97, thresholds=_TH)  # price_no >= 0.95
    assert d.state == NO_TRADE_RESOLVED


def test_yes_asymmetric_opportunity():
    # p_yes(>=18) = 0.85; price_yes 0.50 -> edge_yes 0.35 >= min_edge_yes.
    f = ForecastRow(prob_dist=_PD, confidence_score=0.90, spike_risk=0.0)
    d = decide(f, _C, price_yes=0.50, price_no=0.50, thresholds=_TH)
    assert d.state == OPPORTUNITY_ASSYMETRIC and d.side == "BUY_YES"
    assert d.edge_yes > 0.05


def test_buy_no_when_no_edge_and_spike_low():
    # Contract "<=16": p_yes small -> p_no large; price_no cheap -> edge_no positive.
    c = ContractRange(k_lo=None, k_hi=16)  # p_yes = 0.05, p_no = 0.95
    f = ForecastRow(prob_dist=_PD, confidence_score=0.90, spike_risk=0.0)
    d = decide(f, c, price_yes=0.90, price_no=0.50, thresholds=_TH)
    assert d.state == BUY_NO and d.side == "BUY_NO"


def test_no_edge_stays_out():
    # Fairly priced YES: edge_yes ~ 0, edge_no ~ 0 -> no_edge.
    f = ForecastRow(prob_dist=_PD, confidence_score=0.90, spike_risk=0.0)
    d = decide(f, _C, price_yes=0.85, price_no=0.15, thresholds=_TH)
    assert d.state == NO_TRADE and d.reason == REASON_NO_EDGE


def test_confidence_has_spike_risk_signal():
    assert "neg_spike_risk" in PHI_NAMES and len(PHI_NAMES) == 6


def test_confidence_accepts_spike_risk_without_breaking():
    rng = np.random.default_rng(0)
    n = 80
    pds = [{17: 0.2, 18: 0.6, 19: 0.2} for _ in range(n)]
    lo = [17] * n
    hi = [19] * n
    p50 = rng.normal(18.0, 0.3, n).tolist()
    y = rng.integers(0, 2, n).tolist()
    spike = rng.uniform(0, 1, n).tolist()
    fit = fit_confidence(pds, lo, hi, p50, y, spike_risk=spike)
    s = confidence_score(fit, pds, lo, hi, p50, spike_risk=spike)
    assert s.shape == (n,) and np.all((s >= 0) & (s <= 1))
    # spike_risk=None path still works (backward compatible)
    s2 = confidence_score(fit, pds, lo, hi, p50)
    assert s2.shape == (n,)
