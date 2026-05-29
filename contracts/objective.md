# Contract: Trading objective function (OBJECTIVE_VERSION = 1.0)

> Source: REQ-DEC-3, REQ-MET-6. Frozen on 2026-05-29.

## Selected objective (v1)

```
maximise   EV_realised(test_split)
subject to
    max_drawdown_realised <= 5.0% of initial bankroll,
    coverage >= 25%,
    n_trades_per_month >= 5,
    spike_block_violation_rate < 1.0%
```

## Variables

- `EV_realised(test_split)`: cumulative PnL on the test split, computed via `core/decision/shadow_exec.py` under `EXECUTION_VERSION` 1.0.
- `max_drawdown_realised`: peak-to-trough drawdown of the equity curve in absolute units.
- `coverage`: share of `(date_local, cp_utc)` pairs in which a non-`NO_TRADE` decision was emitted, over the count of pairs with `confidence_score >= min_confidence`.
- `spike_block_violation_rate`: share of trades where `spike_risk >= threshold_spike` was traded.

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
