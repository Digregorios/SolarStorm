# Scope: forecast_error_taxonomy (T-10-3)

> `scope_version = 1.0` (frozen 2026-05-31). Phase 10 (post-calibration), read-only analysis.

## Objective

We know: the point forecast is strong, the analog arm adds little, a calibrated 80% IC is not
recoverable. So the next real improvement must target WHERE the point still errs. Build the failure map:
break the Ridge point error (|y_int - pred_int|, signed error, and bracket-miss rate) by strata and RANK
the largest remaining error pockets, walk-forward 2023/24/25, operational CP (and note per-CP where cheap).

## Strata (all EX-ANTE / diagnostic; available at CP or as honest post-hoc grouping)

month/season; CP; wind quadrant at CP (southerly/northerly); rain-persistence path; s_to_n transition;
predicted-risk regime (calm/non_calm via late_warming_risk); delta_06_to_cp magnitude; analog_confidence
band; NWP-residual magnitude (if panel has it); and the DIAGNOSTIC truth strata (late-warming, Tmax-already-
reached) clearly labelled as post-hoc.

## Deliverable

`scripts/evaluate_error_taxonomy.py` (reuse Ridge + panel + late_warming_risk) +
`reports/model_error_taxonomy.md` (+ `.json`) with: per-stratum n, mean |error|, signed bias,
bracket-miss rate; and an explicit RANKED list: "the 5 largest remaining error pockets are ..." with the
share of total error each accounts for. No gate (it is a diagnosis), but it MUST be honest about which
strata are ex-ante actionable vs post-hoc only.

## Use

The ranked pockets directly seed the NEXT predictor improvement (e.g. a targeted feature or arm for the
worst ex-ante pocket) - replacing guesswork with evidence.

## Scope

ALLOWED: `scripts/evaluate_error_taxonomy.py` (new), `reports/model_error_taxonomy.{md,json}` (new).
Reuse (read-only) ridge_band, training_panel, climatology, late_warming_risk, eval/metrics.
FORBIDDEN: decide.py, decision/**, Polymarket/odds, execution, any contract change, calibration re-opening.
Read-only; no model/threshold change.
