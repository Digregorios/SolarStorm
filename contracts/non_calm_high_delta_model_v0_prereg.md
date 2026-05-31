# Preregistration: non_calm_high_delta_model_v0 (T-11-2)

> `prereg_version = 1.0` (frozen 2026-05-31, DESIGN-FIRST - implementation is a separate later step).
> Phase 11. Rule: "Do not calibrate, do not execute, do not operate Polymarket. Reduce error in the
> ex-ante non_calm/high-delta pocket with walk-forward + honest kill."

## Origin (evidence, not guess)

`reports/model_error_taxonomy.md` (T-10-3) ranked the largest remaining ex-ante error pockets:
non_calm regime (73% of total |error|, MAE 0.732, n=765), then high/mid `delta_06_to_cp` (47%/38%),
southerly (33%); worst per-row on s_to_n transition (0.949) and January (0.989). T-9-1's analog arm
already touches non_calm but with a SMALL gain. This task asks: is there a targeted causal correction
that reduces error in this pocket MORE than the analog arm, without hurting calm/stable days?

## Operational universe (EX-ANTE only)

Acts on days where, at the CP: `predicted_risk >= c30` (non_calm, the canonical calm_day_filter c30 =
train P30) AND `delta_06_to_cp >= delta_mid_threshold` (train-quantile, e.g. >= train P50 of delta_06).
Both are CP-available. NEVER the truth-derived late-warming stratum. Calm / low-delta days are
untouched (passthrough Ridge) by construction.

## Candidate correction (pick ONE to implement; the others are explicitly deferred)

Pre-registered single hypothesis for v0 (avoid a random search):
**H1 - regime-split residual:** fit a SECOND small residual model (Ridge or shallow LGBM) on the
non_calm/high-delta TRAIN rows only, targeting `tmax_int - ridge_pred`, using the existing causal
features + the high-value taxonomy signals (delta_06_to_cp, southerly_at_cp, s_to_n, rain_persistence,
month). Final pred on a pocket day = `ridge_pred + regime_residual`; off-pocket = `ridge_pred`.
Deferred alternatives (NOT in v0; would need their own prereg): interaction features in the main Ridge;
a mixture-of-experts calm-vs-noncalm; an NWP-residual split by regime (blocked on T-11-1 backfill).

Frozen: c30 = train P30; delta threshold = train P50 of delta_06_to_cp; one residual model, seed 42,
no per-split tuning of thresholds or model hyperparameters beyond the existing alpha-grid rule.

## GATE (GO)

ALL of, walk-forward 2023/24/25, operational CP:
1. MAE OR RPS improves on the EX-ANTE non_calm/high-delta pocket in >= 2/3 splits.
2. Aggregate (all days) MAE does not increase by > 0.02 degC AND bracket-match drop <= 0.005 per split.
3. Calm / off-pocket days are unchanged (passthrough verified - identical metrics).
4. The pocket gain is LARGER than T-9-1's analog-arm pocket gain (else the analog arm already suffices
   and this adds complexity for nothing -> KILL).
5. No truth-derived strata in the gate; causal; deterministic; reproducible.

## KILL

- Gain only on the truth-derived late-warming stratum, not the ex-ante pocket.
- Improves the pocket but degrades the aggregate beyond tolerance.
- Gain <= the analog arm's (no marginal value).
- Needs per-split tuning, or leaks truth.

## Scope (when implemented, separate step)

ALLOWED (future impl): `core/models/regime_residual.py`, `scripts/evaluate_non_calm_high_delta.py`,
`reports/non_calm_high_delta_model_v0.{md,json}`. Reuse ridge_band, training_panel, late_warming_risk,
eval/metrics. FORBIDDEN: decide.py, decision/**, Polymarket/odds, execution, any calibration code, any
contract/threshold change, re-tuning T-9-1. Predictor-only.

## What this prereg does NOT do

It does NOT implement the model (design-first, per the reviewer). It freezes the hypothesis, the
ex-ante universe, the constants, and the GO/KILL gate so the later implementation cannot become a
random search. It may proceed in parallel with the ECMWF backfill (T-11-1) since H1 uses obs features,
not NWP; an NWP-residual-by-regime variant is explicitly deferred until the backfill lands.
