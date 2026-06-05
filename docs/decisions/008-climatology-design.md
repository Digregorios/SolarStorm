# ADR-008: Climatology Baseline Design

- **Date:** 2026-06-04
- **Status:** Accepted

## Context

A climatology baseline is an essential null model: it encodes "what you would predict if you only knew the date." For Wellington Airport, Tmax varies systematically by season (winter ~12 C, summer ~20 C) and day-to-day due to synoptic variability.

The baseline must be fit on training data only (walk-forward expanding window) and must never see test dates. It must handle sparse data gracefully (early training years with few observations per day-of-year). It must be smooth enough to avoid overfitting to individual days but sharp enough to capture seasonal transitions.

## Decision

**DOY-smoothed mean via circular convolution (31-day window) with linear interpolation and circular wrap, plus monthly percentiles.**

Implemented in `solarstorm/baselines/_climatology.py`:

### Algorithm

1. **Train-only filter:** `date_local` between `train_start` and `train_end`, `day_complete == True`, `tmax_int` not null.
2. **Minimum 365 training days required** (raises `ValueError` otherwise).
3. **Daily means:** Group by day-of-year (1-366), compute mean `tmax_int`.
4. **Linear interpolation:** Fill missing DOYs via `np.interp` with NaN mask -- handles leap days and sparse early data.
5. **Circular wrap:** `raw_means[0] = raw_means[366]` so Jan 1 neighbors Dec 31 in the smoothing window.
6. **Circular convolution:** 31-day uniform kernel, `mode='valid'` on padded array (`np.concatenate([end, array, start])`). This produces smooth DOY curves without edge artifacts.
7. **Monthly statistics:** Per-month mean, p10, p50, p90 from the training data.

The `Climatology` dataclass stores both `by_doy: dict[int, float]` (DOY -> smoothed mean) and `by_month: dict[int, dict]` (month -> percentiles). Query methods: `tmax_dec_for(date)` returns DOY mean with monthly fallback; `percentiles_for(date, p_low, p_high)` returns monthly percentiles.

### Ladder Level

This is **L2** (climatology) on the baseline ladder, between L1 (dminus1) and L4 (empirical conditional). It answers: "does the model beat just knowing what the date is?"

## Alternatives Considered

1. **Simple monthly means:** Use one value per month. Rejected -- loses within-month seasonal trend (e.g., early December vs late December differ by several degrees in Wellington).
2. **Harmonic regression:** Fit sin/cos annual harmonics. Rejected -- imposes sinusoidal shape that may not match Wellington's asymmetric seasonal cycle.
3. **Gaussian kernel smoothing:** Use a Gaussian-weighted window instead of uniform. Rejected -- adds complexity without clear benefit for a 31-day window where edges are already handled by circular wrap.
4. **GAM/spline:** Generalized additive model with DOY smooth. Rejected -- circular convolution with linear interpolation is simpler, more transparent, and sufficient for a baseline.

## Consequences

### Enabled
- Smooth seasonal cycle without edge artifacts (circular wrap handles Dec-Jan transition).
- Robust to sparse data (interpolation fills gaps, minimum 365-day guard).
- Monthly percentiles provide distributional information (p10/p90 range = "normal" Tmax range for that month).

### Prevents
- Overfitting to individual days (31-day smoothing).
- Winter/summer boundary artifacts (circular convolution).
- Training on test dates (walk-forward `train_end` parameterization).

## References

- `solarstorm/baselines/_climatology.py` -- `fit_climatology()`, `Climatology`
- `solarstorm/__main__.py` -- `baselines` and `leaderboard` commands use train-only windows
