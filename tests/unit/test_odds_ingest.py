"""Live odds ingestor: slug/url derivation + bracket parse (offline; no network)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from core.decision.market_map import ContractRange
from core.ingest.odds import event_slug, event_url, parse_event

_CP = datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc)


def test_slug_and_url_pattern():
    assert event_slug("Wellington", date(2026, 5, 31)) == "highest-temperature-in-wellington-on-may-31-2026"
    assert event_url("Wellington", date(2026, 1, 5)).endswith("highest-temperature-in-wellington-on-january-5-2026")
    # multi-word city slugified
    assert event_slug("New York", date(2026, 12, 25)) == "highest-temperature-in-new-york-on-december-25-2026"


def _market(title, yes, no):
    return {"groupItemTitle": title, "outcomes": '["Yes", "No"]',
            "outcomePrices": json.dumps([str(yes), str(no)]), "bestAsk": yes + 0.001}


def _payload():
    return [{"markets": [
        _market("11\u00b0C or below", 0.0005, 0.9995),
        _market("18\u00b0C", 0.465, 0.535),
        _market("21\u00b0C or higher", 0.006, 0.994),
    ]}]


def test_parse_event_maps_bracket_ranges_and_prices():
    raw = json.dumps(_payload()).encode("ascii")
    snap = parse_event(_payload(), slug="s", cp_utc=_CP, raw=raw)
    assert len(snap.brackets) == 3 and len(snap.sha256) == 64
    below, exact, higher = snap.brackets
    assert below.contract == ContractRange(k_lo=None, k_hi=11)
    assert exact.contract == ContractRange(k_lo=18, k_hi=18)
    assert higher.contract == ContractRange(k_lo=21, k_hi=None)
    assert exact.price_yes == pytest.approx(0.465) and exact.price_no == pytest.approx(0.535)


def test_parse_event_rejects_empty():
    with pytest.raises(ValueError):
        parse_event([], slug="s", cp_utc=_CP, raw=b"[]")
