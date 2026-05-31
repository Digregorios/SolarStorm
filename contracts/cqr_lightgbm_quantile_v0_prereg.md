# Preregistration: cqr_lightgbm_quantile_v0 (T-11-8) - PLANNED / research-backed

> `prereg_version = 1.0` (frozen 2026-06-01). Phase 11. **STATUS: PLANNED - DO NOT EXECUTE before
> T-11-5 (ECMWF/ensemble point gain) and T-11-6 (two-model spread feasibility), unless explicitly
> directed.** This freezes the hypothesis + gate now; implementation is a later, gated step.

## Why this reopens calibration WITHOUT contradicting the closure

The Phase 5 / T-9-3 / T-9-5 closures killed the paradigm: strong CENTER -> post-hoc (symmetric/signed)
band / conformal residual -> integer quantization. Those are settled-dead. CQR (conformalized quantile
regression) changes the OBJECT LEARNED:

> learn ADAPTIVE quantile bounds q_lo(x), q_hi(x) directly (LightGBM quantile loss) -> conformalize the
> BOUNDS (not a residual around a center) -> emit the integer interval.

This is a genuinely new hypothesis (literature-backed: Romano et al. 2019 CQR), targeting exactly what
Phase 5 could not: heteroscedastic, asymmetric, late-CP over-covering intervals. It is NOT a
continuation of the dead center+band attempts.

## Honest caveat (recorded before running)

The final target is still INTEGER Tmax. So: integer granularity persists (the T-9-5 lesson - native
integer still over-covered), the REQ-AUD-5 het gate may STILL be hard, and `Q` on the final bound can
re-add slack. CQR may improve interval SHAPE a lot yet still not pass REQ-AUD-5. The gate is unchanged;
no loosening. If CQR also fails, accept EVEN MORE strongly that a calibrated 80% integer IC is not
recoverable at this granularity.

## Method (when executed)

Per split, per CP: fit two LightGBM quantile models q_lo=q(0.10), q_hi=q(0.90) on TRAIN; CQR-conformalize
the bounds on the held-out CALIB slice (additive conformity correction E_i = max(q_lo-y, y-q_hi),
quantile of E at level 1-alpha); emit integer interval [Q(q_lo - E), Q(q_hi + E)] (hi >= lo enforced).
Features = the BEST available set at execution time: current obs features + GFS + ECMWF (+ two-model
spread/disagreement IF T-11-6 gave GO). Deterministic (seed 42, lightgbm deterministic=True).

## Baselines (same rows)

Phase 5 v1.0 signed conformal; `ridge_conformal_minimal` (the stopgap); T-9-3 regime-conditional.

## GATE (GO) - REQ-AUD-5 UNCHANGED

ALL of, walk-forward 2023/24/25, per split (reuse `core/eval/gates_phase5.heteroscedasticity_gate`):
1. Global IC80 coverage in [0.78, 0.86] in >= 2/3 splits.
2. REQ-AUD-5 het gate (per-width-quartile coverage in [0.70,0.90]) PASSES in >= 2/3 splits.
3. Mean width does not exceed `ridge_conformal_minimal` mean width (no passing-by-inflation).
4. RPS / log-score not materially worse (<= +2% rel) than the v1.0 baseline.
5. Improves especially in late-CP / non_calm / high-delta strata.
6. train/calib/test disjoint; deterministic; no per-split tuning of quantile levels.

## KILL

Passes only by widening; passes global but fails conditional; quantile levels chosen looking at test;
still over-covers from granularity; degrades the point/RPS; LightGBM non-reproducible.

## Scope (when implemented)

ALLOWED: `core/models/quantile_lgbm.py`, `scripts/evaluate_cqr_lightgbm_quantile.py`,
`reports/calibration/cqr_lightgbm_quantile_v0.{md,json}`. Reuse training_panel, eval/gates_phase5,
eval/metrics, conformal helpers as needed.
FORBIDDEN: `core/cli/decide.py`, `core/decision/**`, Polymarket/odds, execution, any REQ-AUD-5 loosening,
any contract/threshold change.

## Queue position (reviewer-directed)

1. T-11-5 ECMWF/ensemble point gain. 2. T-11-6 two-model spread feasibility.
3. T-11-8 CQR (this) - executed LAST, fed the best feature set incl. ECMWF (+ spread if T-11-6 GO),
   because CQR is underestimated if run before the new NWP features exist.
