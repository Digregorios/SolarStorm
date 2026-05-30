# Contract: Shadow execution parameters (EXECUTION_VERSION = 1.0)

> Source: REQ-MET-5, design section 10.1. Frozen on 2026-05-30.

## Parameters

| Parameter                 | Value                        | Notes                                      |
|---------------------------|------------------------------|--------------------------------------------|
| `fee_bps`                 | 200                          | 2% per side (entry + exit)                 |
| `slippage_model`          | `taker_at_quote`             | No improvement; pay quoted price           |
| `entry_price_rule`        | `ask`                        | Single rule per version                    |
| `fill_rule`               | `assume_full_fill`           | Ablation: partial_fill_with_min_size       |
| `position_sizing`         | `1 unit notional`            | No Kelly / no martingale in v1             |
| `max_concurrent_positions`| `1 per market per CP`        | One trade active per market per checkpoint |
| `time_in_force`           | `cancel_unfilled_at_next_cp` | Unfilled orders cancelled at next CP       |

## Semantics

- `fee_bps` is charged on BOTH entry and exit (total round-trip = 2 * fee_bps).
- `taker_at_quote`: BUY YES pays `price_yes`; BUY NO pays `price_no`.
- `assume_full_fill`: every order is assumed fully filled at the quoted price.
- `partial_fill_with_min_size`: experimental; requires `min_fill_fraction` param.
- PnL formula: `(payoff - entry_price) * notional - 2 * fee` where
  `fee = entry_price * notional * fee_bps / 10000`.

## Change protocol

Bump `EXECUTION_VERSION` and re-run shadow backtest; old results are invalidated.
