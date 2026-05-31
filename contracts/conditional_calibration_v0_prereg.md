# Preregistration: conditional_calibration_v0 (T-9-3) - the "roof"

> `prereg_version = 1.0` (frozen 2026-05-31, before implementation). Phase 9 predictor improvement.
> Guiding rule: "Do not build Polymarket. Do not build execution. Improve the Tmax predictor /
> calibrate its distribution in causal walk-forward, or honestly kill the hypothesis."

## Why this is the roof (and an honest prior)

The point forecast is strong (Ridge beats baselines; T-9-1 added a small high-risk gain). The OPEN
problem is the DISTRIBUTION / interval: Phase 5 closed NOT READY because the binding REQ-AUD-5
heteroscedasticity gate (every IC80 width-quartile must cover in [0.70,0.90], per split) never
passed - the late-CP (22Z/23Z) moderately-wide bin structurally OVER-covers.

HONEST PRIOR (recorded before running): Phase 5 already tried global scaling (A1), Mondrian
conditional-by-SIGMA (A3), entropy/margin difficulty axes (P/P'), and randomized rounding (D1).
All failed; the closure concluded the over-coverage is STRUCTURAL ("reshaping tails relabels slack,
it does not remove it"). So the a-priori probability that ANY reshaping passes the gate is LOW. This
experiment is justified ONLY because it conditions on a genuinely NEW axis not tried before:

> **ex-ante REGIME (calm / non-calm), from the validated late-warming risk model**, NOT interval
> width and NOT sigma buckets (A3). calm vs non-calm is exactly the structural split the bias audit
> + calm_day_filter_v0 isolated. This folds T-9-2 (calm) INTO the calibration design as the reviewer
> directed, rather than as a separate point arm.

The deliverable is valuable EVEN IF the gate stays red: it will say definitively whether the
structural slack lives in a specific ex-ante regime (actionable diagnosis), or is irreducible with
local features (-> the next candidate is NWP-spread sigma or a different object).

## Object calibrated

The integer IC80 bracket `[lo_int, hi_int]` for Tmax, the SAME object REQ-AUD-5 evaluates (so the
conformal guarantee is not broken by calibrating one object and scoring another - the v1.0 lesson).
Point forecast = the existing Ridge band-aware latent (per phase3 machinery), unchanged.

## Method (regime-conditional split-conformal)

Per split, per CP, partition calibration rows by the EX-ANTE regime:
```
regime(day) = "calm"      if predicted_risk(day) <  c30   (calm_day_filter_v0 cutpoint, train P30)
            = "non_calm"  otherwise
```
`predicted_risk` from `core/models/late_warming_risk` (CP-available features only). c30 frozen on
TRAIN. Fit a SEPARATE signed split-conformal calibrator (reuse `core/calibration/conformal.fit_conformal`
/ `apply_conformal`, method="signed") per (cp, regime) on the held-out calib slice; fall back to
per-cp then pooled when a (cp,regime) cell has < `min_calib` rows. Coverage target 0.80.

Frozen: coverage=0.80, method="signed", min_calib=30, the two regimes above, c30 = train P30 of
predicted risk. NO per-split tuning of any of these.

## Baselines (mandatory comparison, per the reviewer)

1. Phase 5 v1.0 (unconditional signed conformal) - the prior baseline.
2. `ridge_conformal_minimal` per-CP IC80 (the defensible stopgap; coverage 0.86-0.91).
Report BOTH against the regime-conditional method on identical rows.

## GATE (GO to promote regime-conditional calibration)

ALL of (reuse `core/eval/gates_phase5.heteroscedasticity_gate`, per split, never pooled):
1. Global IC80 coverage in [0.78, 0.86] in >= 2/3 splits.
2. REQ-AUD-5 het gate (per-width-quartile coverage in [0.70,0.90]) PASSES in >= 2/3 splits, OR
   the per-REGIME coverage is in [0.74,0.86] for BOTH regimes in >= 2/3 splits (the conditional
   target, since the new axis is regime not width).
3. Mean IC80 width does NOT exceed the v1.0 baseline mean width by more than +0.5 bracket
   (no passing-by-inflation).
4. RPS / log-score on the discrete dist not materially worse than v1.0 (<= +2% relative) where
   applicable; if the method only adjusts the interval (not the full pmf), report RPS as n/a with
   justification.
5. Causal + reproducible: regime is ex-ante, calib/test split honored, deterministic.

## KILL

- Passes global but fails BOTH the width-quartile AND the per-regime conditional target.
- Passes coverage only by inflating width beyond the tolerance.
- Needs per-split manual tuning.
- Uses a truth-derived regime to calibrate.
- Improves the interval but destroys the pmf (RPS materially worse).

If KILL: record WHICH regime carries the residual over-coverage (the diagnostic value), and name the
next candidate (NWP-spread sigma, or accept ridge_conformal_minimal as the operational stopgap).

## Scope (files implementation may touch)

ALLOWED: `scripts/evaluate_conditional_calibration.py` (new), `reports/calibration/conditional_calibration_v0.{md,json}` (new),
and a thin NEW helper in `core/calibration/` ONLY if needed (prefer reusing `fit_conformal`/`apply_conformal`
+ `heteroscedasticity_gate` as-is). Reuse (read-only) `late_warming_risk`, `ridge_band`, `training_panel`,
`climatology`, `eval/metrics`, `eval/gates_phase5`.
FORBIDDEN: `core/cli/decide.py`, `core/decision/**`, any Polymarket/odds, any execution code, any
contract/threshold change, any gate loosening, reopening/editing the Phase 5 closure verdict.

## What this does NOT do

No execution wiring; no change to the production forecast/IC path; does not reopen Phase 5 (this is a
NEW Phase-9 conditional experiment over the same object, gate reused unchanged). Promotion into serving
is a separate later step.
