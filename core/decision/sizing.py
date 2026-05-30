"""Live EV + Kelly sizing from the model prob_dist and a LIVE odds snapshot (REQ-MET-5).

Polymarket odds are live-only context captured at the forecast CP (REQ-DEC-4); there is NO
historical odds dataset and NO realized-EV backtest. This module turns a model probability
``p`` (from ``market_map.p_yes`` over the forecast ``prob_dist``) plus the moment's price into
an expected value per unit notional and a fractional-Kelly stake.

Binary-contract payout convention (Polymarket): buying a side at ``price`` in [0,1] pays 1 if
the side resolves YES, else 0. Net per unit notional, with a per-side fee ``f`` (entry+exit):

    win  = (1 - price) - f
    loss = -price - f
    EV   = p*win + (1-p)*loss = p - price - f          (f = 2 * price * fee_bps/1e4)

Kelly for a 1:0/0:1 binary at decimal-odds ``b = (1-price)/price`` is ``(p*b - (1-p))/b``,
scaled by ``kelly_cap`` and floored at 0 (never bet a negative edge). All deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.contracts.execution import ExecutionContract, default_execution_contract


@dataclass(frozen=True)
class SizingResult:
    """Live EV + stake for one side of one contract."""

    side: str            # "BUY_YES" | "BUY_NO"
    p_model: float       # model probability the side resolves YES
    price: float         # live entry price for the side
    fee: float           # total fee per unit notional (entry + exit)
    expected_value: float
    kelly_fraction: float  # capped, floored at 0
    stake: float           # notional to deploy under the contract's sizing rule


def _fee_per_unit(price: float, fee_bps: int) -> float:
    """Total fee per unit notional, charged on entry and exit (design 10.1)."""
    return 2.0 * price * fee_bps / 1e4


def expected_value(p_model: float, price: float, *, fee_bps: int = 200) -> float:
    """EV per unit notional of buying a binary side at ``price`` with win-prob ``p_model``."""
    if not (0.0 <= p_model <= 1.0):
        raise ValueError(f"p_model must be in [0,1]; got {p_model}")
    if not (0.0 < price < 1.0):
        raise ValueError(f"price must be in (0,1); got {price}")
    return p_model - price - _fee_per_unit(price, fee_bps)


def kelly_fraction(p_model: float, price: float, *, kelly_cap: float = 0.25) -> float:
    """Capped fractional Kelly for a binary contract; 0 when the edge is non-positive."""
    if not (0.0 <= p_model <= 1.0):
        raise ValueError(f"p_model must be in [0,1]; got {p_model}")
    if not (0.0 < price < 1.0):
        raise ValueError(f"price must be in (0,1); got {price}")
    b = (1.0 - price) / price  # net decimal odds
    f_star = (p_model * b - (1.0 - p_model)) / b  # full Kelly
    if f_star <= 0.0:
        return 0.0
    return min(f_star, 1.0) * kelly_cap


def size_side(
    side: str,
    p_yes: float,
    price: float,
    *,
    contract: ExecutionContract | None = None,
) -> SizingResult:
    """Size ONE side at the live price under the frozen execution contract.

    ``p_yes`` is the model probability the contract resolves YES (from market_map). For
    ``BUY_NO`` the win-prob is ``1 - p_yes`` and the price is the NO price. ``stake`` is
    ``kelly_fraction`` when ``position_sizing == 'fractional_kelly'``, else a flat 1 unit
    (0 when EV <= 0 so a flat-sized book never takes a negative-edge trade).
    """
    if side not in ("BUY_YES", "BUY_NO"):
        raise ValueError(f"side must be BUY_YES or BUY_NO; got {side!r}")
    cfg = contract or default_execution_contract()
    p_win = p_yes if side == "BUY_YES" else 1.0 - p_yes
    ev = expected_value(p_win, price, fee_bps=cfg.fee_bps)
    kf = kelly_fraction(p_win, price, kelly_cap=cfg.kelly_cap)
    if cfg.position_sizing == "fractional_kelly":
        stake = kf
    else:  # 1_unit_notional: take 1 unit only on a positive edge, else stay flat
        stake = 1.0 if ev > 0.0 else 0.0
    return SizingResult(
        side=side, p_model=p_win, price=price,
        fee=_fee_per_unit(price, cfg.fee_bps),
        expected_value=ev, kelly_fraction=kf, stake=stake,
    )


def size_book(
    prob_dist: dict[int, float],
    brackets,
    *,
    contract: ExecutionContract | None = None,
):
    """Live: best EV side per bracket, given the model prob_dist + a live OddsSnapshot.

    ``brackets`` is an iterable of objects exposing ``.contract`` (a ContractRange), ``.label``,
    ``.price_yes`` and ``.price_no`` (i.e. ``OddsSnapshot.brackets``). For each bracket the
    model ``p_yes`` is summed over the range, both sides are priced, and the side with the
    higher (positive) EV is kept; brackets with no positive-EV side are skipped. Returns a list
    of ``(label, SizingResult)`` sorted by descending stake -- the live sizing book.
    """
    from core.decision.market_map import p_yes as _p_yes  # local import: avoid cycle at module load

    cfg = contract or default_execution_contract()
    book: list[tuple[str, SizingResult]] = []
    for b in brackets:
        py = _p_yes(prob_dist, b.contract)
        yes = size_side("BUY_YES", py, b.price_yes, contract=cfg)
        no = size_side("BUY_NO", py, b.price_no, contract=cfg)
        best = yes if yes.expected_value >= no.expected_value else no
        if best.expected_value > 0.0 and best.stake > 0.0:
            book.append((b.label, best))
    book.sort(key=lambda t: t[1].stake, reverse=True)
    return book


__all__ = [
    "SizingResult",
    "expected_value",
    "kelly_fraction",
    "size_side",
    "size_book",
]
