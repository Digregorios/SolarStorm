# Contract: Trading objective function (OBJECTIVE_VERSION = 1.0)

> Source: REQ-DEC-3, REQ-MET-6. Frozen on 2026-05-29. Scope-corrected 2026-05-30:
> Polymarket odds are LIVE-only context (no historical odds dataset), so the OFFLINE
> objective is odds-free; EV/Kelly are a LIVE product of the forecast + the moment's odds.

## Selected objective (v1)

### Offline (model promotion + threshold tuning; odds-free)

```
maximise   bracket_match_when_traded(test_split)
subject to
    coverage >= 25%,
    forecast-quality gates pass (RPS, ECE, SS-vs-persistence, anti-nowcaster REQ-AUD-2)
```

This is the ONLY objective computable offline: there is no historical odds dataset, so a
realized-EV backtest over the test split does not exist. Model promotion is decided here.

### Live (at the forecast CP; uses the moment's odds)

```
per live forecast at cp_utc:
    EV_yes = p_yes * (1 - price_yes) - (1 - p_yes) * price_yes - fees   (and symmetric EV_no)
    size   = fractional_kelly(p, price, kelly_cap)   # 0 when EV <= 0
subject to   max_concurrent_positions, time_in_force   (contracts/execution.md)
```

`EV` and Kelly sizing are computed at forecast time from the model `prob_dist` and the live
odds snapshot (REQ-DEC-4); they are NOT an offline training/selection criterion.

## Variables

- `bracket_match_when_traded(test_split)`: share of traded `(date_local, cp_utc)` pairs whose
  `p50_int` hit the realized bracket, over the test split (odds-free).
- `coverage`: share of `(date_local, cp_utc)` pairs with a non-`NO_TRADE` decision, over the
  count of pairs with `confidence_score >= min_confidence`.
- `EV_yes/EV_no` (LIVE): expected value per unit notional given the live price and the model
  `p_yes`, net of `fee_bps` (contracts/execution.md).
- `fractional_kelly` (LIVE): Kelly fraction scaled by `kelly_cap`, floored at 0 when `EV <= 0`.

## Tunable thresholds (REQ-DEC-3, REQ-MET-6)

| Threshold              | Search range  | Step  |
|------------------------|---------------|-------|
| `min_edge_yes`         | [0.01, 0.10]  | 0.005 |
| `min_edge_no`          | [0.01, 0.10]  | 0.005 |
| `no_too_expensive`     | [0.85, 0.99]  | 0.01  |
| `min_confidence`       | [0.30, 0.80]  | 0.05  |
| `threshold_spike`      | [0.10, 0.50]  | 0.05  |

## Hard rules

- Tuning of any other parameter (model `tau`, `safety_margin`, calibration window, regime count) is **forbidden** under this objective. Those are part of `MODEL_VERSION`.
- The TEST split is evaluated **once** per `threshold_set_id`. Multiple test evaluations invalidate the version.
- Nested walk-forward CV per REQ-MET-6.

## Change protocol

Bump `OBJECTIVE_VERSION` and re-run nested walk-forward; new `threshold_set_id` is required.
