# Preregistration: calm_day_filter_v0

> `prereg_version = 1.0` (frozen 2026-05-31, before running).

## Motivation (design discovery, not failure)

`risk_model_v0/v0.1` failed their gates as HIGH-risk detectors, but the LOW (protective) bucket
was robust and consistent OOS. Per `references/code-reviews/update.txt` the right move is to
re-frame the component around the signal that actually exists: a CALM-DAY / suppression filter.
This does NOT promote risk_model_v0.1 and does NOT loosen its gate - it is a new, separately
gated component with a different objective (identify days where material late-warming is reliably
LOW).

## Objective

Identify days where ``P(material_late_warming = k_eod - k_cp >= 2)`` is reliably LOW, so the
forecast layer can (later, gated) trust persistence/Ridge more, avoid upward over-correction, and
narrow the IC only where conformal validates. NOTHING in the forecast is changed here.

## Model / features (same as the validated precursors; no new fitting hypothesis)

Reuse `core.models.late_warming_risk` (logistic + isotonic) on the gate-passing precursors:
`delta_06_to_cp, southerly_at_cp, rain_persistence_path, month_sin, month_cos`. The filter is the
LOW band of the predicted risk; `s_to_n` is NOT included (did not help v0.1b).

## Calm-day rule (frozen)

`calm_day = predicted_risk < c_low`, where ``c_low`` is the 30th percentile of the TRAIN predicted
risk (fit on train, applied on test). (Bottom-30% band; the same train-quantile approach as v0.1
but only the LOW edge matters here.)

## Split protocol

Walk-forward 2023/2024/2025; fit on train before the last 120 d, isotonic calib on the held-out
120 d, evaluate on the test year. ``c_low`` from train predicted risk. Test never seen in fit.

## GATE (pre-registered; accept if ALL hold in >= 2/3 splits)

```
1. calm-bucket obs-rate(material_lw) <= 0.65x base        (strong suppression)
2. calm-bucket n >= 25 per split
3. precision for "no material late-warming" on calm days >= 0.75   (= 1 - obs-rate >= 0.75)
4. Brier of the full calibrated model < base-rate Brier
5. (optional report) monotone low <= mid <= high if buckets shown
6. no post-CP leak (build_features uses ts<cp; unit-tested)
```
Focus is the LOW bucket; high-risk sharpness is explicitly NOT gated (that is the analog/NWP
arm's job, Etapa 3).

## Acceptance / kill

ACCEPT calm_day_filter_v0 if all gates hold >= 2/3 splits -> the calm flag may LATER feed (each
gated): narrower IC on calm days (if conformal validates), reduced late-spike weight, higher
persistence/Ridge trust. KILL: if not, leave diagnostic; do not tune thresholds to pass.

## What this does NOT do

No center change, no conditional conformal here, no IC change, no s_to_n. Diagnostic flag only
until a downstream use is separately gated. High-risk detection is deferred to Etapa 3 (analogs).
