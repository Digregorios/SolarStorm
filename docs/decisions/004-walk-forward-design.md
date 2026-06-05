# ADR-004: Walk-Forward Design

- **Date:** 2026-06-04
- **Status:** Accepted

## Context

Time-series cross-validation for a daily forecasting problem cannot use random k-fold splits -- they break temporal ordering and leak future information into training. Standard alternatives (rolling window, expanding window) each have different bias-variance tradeoffs.

The old Wellington project used a single static train/test split, which made it impossible to assess temporal stability and invited overfitting to a specific period.

SolarStorm's forecast horizon is short (same-day Tmax) and the data is 17 years (2009-2026). An expanding-window design maximizes training data while respecting temporal order, and annual test starts ensure full seasonal cycles in every split.

## Decision

**Expanding-window walk-forward with annual test starts and recent holdout windows.**

Implemented in `solarstorm/eval/_walkforward.py`:

```python
def expanding_walk_forward_splits(
    *,
    history_start: dt.date,
    test_starts: list[dt.date],       # Jan 1 of each year from 2014 (or year 5)
    test_length_days: int = 365,       # Full year of test data
    min_train_days: int = 365,         # Minimum 1 year of training
    holdout_windows_days: list[int] | None = None,  # [7, 14, 30] for recent holdouts
) -> list[Split]:
```

Each `Split` contains: `train_start`, `train_end`, `test_start`, `test_end`.

Key design choices:
- **Expanding window** (not rolling): Fixed origin at `history_start`, growing training set. This maximizes data for early years and is appropriate for a problem where older data remains relevant.
- **Annual test starts:** Test periods begin January 1 each year. This ensures each split contains a full seasonal cycle and avoids artifacts from partial-year evaluation.
- **Minimum 5 years training:** The first test year is 2014 (or `history_start + 5 years`). A model trained on fewer than 5 years is unlikely to have seen enough seasonal and ENSO variation.
- **Holdout windows (7/14/30d):** In addition to annual splits, recent fixed-length holdout windows anchored at today's date provide a live-read on current performance.

The test defaults (via `_default_test_starts()` in `_validate.py`): annual Jan-1 splits from `max(first_year + 5, 2014)` through 2025.

## Alternatives Considered

1. **Rolling window (fixed-length):** Train on last N years, test on next year. Rejected -- for a 17-year dataset, discarding early data loses value when older years are climatologically relevant (they contain different ENSO phases).
2. **Purged k-fold:** Blocked cross-validation that groups contiguous days into folds. Rejected -- unnecessary complexity for a daily problem; annual splits are the natural block.
3. **Single chrono-split (2009-2020 train, 2021-2025 test):** Rejected -- masks temporal drift and gives a single metric with no variance estimate.

## Consequences

### Enabled
- Multiple performance estimates (one per test year) with natural variance.
- Temporal stability diagnostics: is performance improving or degrading over time?
- Holdout windows enable operational monitoring without contaminating the validation framework.

### Prevents
- Overfitting to a particular year's weather pattern.
- Data leakage from future dates into training.
- The old project's pattern of a single test split that "looked good enough."

## References

- `solarstorm/eval/_walkforward.py` -- `expanding_walk_forward_splits()`
- `solarstorm/eda/_validate.py` -- `_default_test_starts()`, walk-forward loop
- `solarstorm/eval/_bootstrap.py` -- `bootstrap_ci_diff()` (paired resampling within each split)
