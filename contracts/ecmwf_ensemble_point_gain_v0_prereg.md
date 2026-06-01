# Preregistration: ecmwf_ensemble_point_gain_v0 (T-11-5)

> `prereg_version = 1.0` (frozen 2026-06-01, before implementation). Phase 11. Rule: "Use the 2nd causal
> NWP source to improve the POINT forecast in walk-forward, or honestly kill it. No calibration, no
> execution, no Polymarket."

## Objective

Now that ECMWF is landed (T-11-4/T-11-7, 671/671 days causal), measure whether ECMWF - alone or
ensembled with GFS - improves the Tmax POINT forecast vs the existing models, on identical rows,
walk-forward, per CP and in the high-error pockets the taxonomy (T-10-3) identified.

## Candidates (same rows, same splits)

1. **Ridge base** (no NWP) - the floor.
2. **GFS-residual** (existing Phase-4 residual LGBM, GFS anchor) - the current NWP model.
3. **ECMWF-residual** - same residual-LGBM recipe, ECMWF anchor instead of GFS.
4. **GFS+ECMWF ensemble** - the residual LGBM fed BOTH anchors (mean anchor + both as features), the
   2-model variant the single-source archive could not build before.

Reuse the Phase-4 panel + residual LGBM machinery; only the NWP anchor/feature source changes. Per-split
train-only climatology; causal NWP selection (`run_time <= cp - 60min`, already enforced). Window is the
ECMWF overlap 2024-03..2025-12; report honestly that this is a SHORTER walk-forward than the 2023-2025
point splits (ECMWF archive/backfill start), and use within-window expanding splits (>= 2 test folds).

## Metrics (per CP 20/21/22/23, per split, and pooled-as-labelled-note)

MAE, RMSE, bracket-match, RPS. Strata: ALL; EX-ANTE non_calm (risk>=c30); high_delta_06 (>= train P50);
the intersection non_calm AND high_delta_06 (the T-10-3 top pocket).

## GATE (GO to flag an ECMWF/ensemble candidate point model)

ALL of:
1. ECMWF-residual OR the GFS+ECMWF ensemble improves MAE OR RPS at CP20-22 vs the best of
   {Ridge, GFS-residual} in >= 2/3 within-window splits.
2. Does not regress CP23 MAE by > 0.02 degC vs the best existing model.
3. Material improvement in the non_calm/high_delta pocket (the largest error pocket) - dMAE <= -0.03 or
   dRPS clearly negative in >= 2/3 splits.
4. Causal, deterministic (seed 42, lightgbm deterministic), reproducible; train/calib/test disjoint.
5. No execution / calibration / contract change.

GO = the simplest candidate (prefer ECMWF-residual, then ensemble) meeting 1-4.

## KILL

- ECMWF/ensemble does not beat GFS-residual (the 2nd source adds nothing for the point) -> record that
  ECMWF's value, if any, is for SPREAD (T-11-6), not the point.
- Gain only on truth-derived strata.
- Regresses the aggregate or CP23 beyond tolerance.
- Needs per-split tuning.

## Scope

ALLOWED: `scripts/evaluate_ecmwf_ensemble_point_gain.py` (new), `reports/nwp/ecmwf_ensemble_point_gain.{md,json}`
(new), and a thin reuse of the Phase-4 panel builder with an ECMWF/ensemble anchor (prefer a parameter
on the existing builder over new model code). Reuse ridge_band, residual_lgbm, training_panel,
late_warming_risk, eval/metrics.
FORBIDDEN: `core/cli/decide.py`, `core/decision/**`, Polymarket/odds, execution, any calibration code,
any contract/threshold change. Predictor-only.

## What this does NOT do

No promotion into serving (that needs the consolidated per-CP matrix, T-11-3); no calibration; no spread
work (that is T-11-6). It answers ONLY: does the 2nd NWP source improve the point, and where?
