"""Live Polymarket odds snapshot at the forecast CP (REQ-DEC-4; live-only context).

Polymarket Tmax markets follow a fixed URL/slug pattern for every city+date:

    https://polymarket.com/event/highest-temperature-in-<city>-on-<month>-<day>-<year>

e.g. ``highest-temperature-in-wellington-on-may-31-2026``. The Gamma API exposes the same
event by slug at ``gamma-api.polymarket.com/events?slug=...``; the event holds one ``market``
per integer-degC bracket, each carrying ``groupItemTitle`` (the bracket label), ``outcomes``
(["Yes","No"]) and ``outcomePrices`` (YES/NO as JSON-encoded strings) plus ``bestAsk``.

This module derives the slug/URL deterministically, fetches the live snapshot ONCE (no
historical backfill -- odds only exist at forecast time), maps each bracket label to a
``ContractRange`` (``market_map``), and returns prices + a SHA256 of the raw payload for
provenance. It feeds ``core.decision.sizing`` (EV + Kelly) at the live CP.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx

from core.decision.market_map import ContractRange
from core.io.hashing import sha256_bytes

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
EVENT_URL_BASE = "https://polymarket.com/event"
_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


def event_slug(city: str, d: date) -> str:
    """Deterministic event slug: highest-temperature-in-<city>-on-<month>-<day>-<year>."""
    city_slug = re.sub(r"[^a-z0-9]+", "-", city.strip().lower()).strip("-")
    return f"highest-temperature-in-{city_slug}-on-{_MONTHS[d.month - 1]}-{d.day}-{d.year}"


def event_url(city: str, d: date) -> str:
    return f"{EVENT_URL_BASE}/{event_slug(city, d)}"


def _parse_bracket(title: str) -> ContractRange:
    """Map a bracket label to a ContractRange. '<N> or below' -> k_hi; 'or higher/above' ->
    k_lo; bare '<N>' -> exact. Reads the first integer in the label."""
    m = re.search(r"(-?\d+)", title)
    if not m:
        raise ValueError(f"no integer in bracket title {title!r}")
    k = int(m.group(1))
    low = title.lower()
    if "below" in low or "lower" in low:
        return ContractRange(k_lo=None, k_hi=k)
    if "higher" in low or "above" in low:
        return ContractRange(k_lo=k, k_hi=None)
    return ContractRange(k_lo=k, k_hi=k)


@dataclass(frozen=True)
class OddsBracket:
    """One live bracket contract: range + YES/NO prices."""

    contract: ContractRange
    label: str
    price_yes: float
    price_no: float
    best_ask: float | None


@dataclass(frozen=True)
class OddsSnapshot:
    """A single live-moment snapshot of an event's bracket prices (REQ-DEC-4)."""

    slug: str
    event_url: str
    cp_utc: datetime
    ts_utc: datetime
    sha256: str
    brackets: tuple[OddsBracket, ...]


def parse_event(payload: list, *, slug: str, cp_utc: datetime, raw: bytes) -> OddsSnapshot:
    """Build an OddsSnapshot from a Gamma /events payload (pure; testable offline)."""
    if not payload:
        raise ValueError(f"empty Gamma payload for slug {slug!r}")
    event = payload[0]
    brackets: list[OddsBracket] = []
    for m in event.get("markets", []):
        title = m.get("groupItemTitle")
        if not title:
            continue
        px = json.loads(m["outcomePrices"]) if isinstance(m.get("outcomePrices"), str) else m.get("outcomePrices")
        if not px or len(px) < 2:
            continue
        ba = m.get("bestAsk")
        brackets.append(
            OddsBracket(
                contract=_parse_bracket(title),
                label=title,
                price_yes=float(px[0]),
                price_no=float(px[1]),
                best_ask=float(ba) if ba is not None else None,
            )
        )
    if not brackets:
        raise ValueError(f"no bracket markets parsed for slug {slug!r}")
    return OddsSnapshot(
        slug=slug,
        event_url=f"{EVENT_URL_BASE}/{slug}",
        cp_utc=cp_utc,
        ts_utc=datetime.now(timezone.utc),
        sha256=sha256_bytes(raw),
        brackets=tuple(brackets),
    )


def snapshot_live(city: str, d: date, cp_utc: datetime, *, timeout: float = 30.0) -> OddsSnapshot:
    """Fetch the live odds snapshot for (city, date) at cp_utc. Live-only; one call, no backfill."""
    slug = event_slug(city, d)
    with httpx.Client(timeout=timeout) as client:
        r = client.get(GAMMA_EVENTS, params={"slug": slug})
        r.raise_for_status()
        raw = r.content
    return parse_event(json.loads(raw), slug=slug, cp_utc=cp_utc, raw=raw)


__all__ = [
    "GAMMA_EVENTS",
    "EVENT_URL_BASE",
    "event_slug",
    "event_url",
    "OddsBracket",
    "OddsSnapshot",
    "parse_event",
    "snapshot_live",
]
