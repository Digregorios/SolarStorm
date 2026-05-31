# Preregistration: analog_high_risk_arm_v0 (T-9-1)

> `prereg_version = 1.0` (frozen 2026-05-31, before implementation). Phase 9 predictor improvement.
> Guiding rule: "Do not build Polymarket. Do not build execution. Improve the Tmax predictor in
> causal walk-forward or honestly kill the hypothesis."

## Objective

Improve the Tmax POINT forecast on the high-risk (late-warming) side that Ridge under-serves, by
blending an analog-based estimate into Ridge ONLY where an EX-ANTE causal gate flags the day as
high-risk. The analog retrieval is already validated (`analog_retrieval_audit` g1-g4 PASS;
`analog_quality_v0.1` resolves g5 via `analog_confidence`). This arm turns that retrieval into a
point-forecast correction and measures whether it beats Ridge.

## CRITICAL: ex-ante (causal) vs truth-derived (diagnostic)

The OPERATIONAL gate MUST be available at the CP. It is NEVER "days that actually had late-warming".
- **Operational (ex-ante) high-risk gate:** `predicted_risk(day) >= c30`, where `predicted_risk` is the
  logistic late-warming risk (`core/models/late_warming_risk.predict_risk`, features available at CP)
  and `c30` is the 30th percentile of the TRAIN predicted risk (the `calm_day_filter_v0` cutpoint).
  i.e. the arm acts on NON-CALM days = NOT in the bottom-30% calm band. Fully ex-ante.
- **Diagnostic (truth-derived) stratum:** "material late-warming (truth - k_cp >= 2)" - reported for
  insight ONLY, never used to decide where the arm acts or to compute the GO gate.

If the arm's gain only exists on the truth-derived stratum and not on the ex-ante non-calm stratum,
that is a KILL (it would be unusable live).

## Analog point forecast (causal)

For a test day, retrieve K=50 nearest TRAIN-pool neighbors (pool date < test, train-only standardizer)
using the validated 7-feature causal distance vector
(`k_cp, delta_06_to_cp, southerly_at_cp, rain_persistence_path, s_to_n, month_sin, month_cos`).
```
analog_delta   = smoothed mean over neighbors of (tmax_int - k_cp)          # causal: neighbors are past
analog_pred    = k_cp + analog_delta                                         # analog Tmax estimate
P_analog       = smoothed neighbor late-warming frequency  (as in the audit)
analog_conf    = |P_analog - base_rate_train|                                # the g5-passing quality
```
Anti-leakage (mandatory): neighbor pool strictly date < test day; standardizer + c30 + base_rate fit
on TRAIN only; NO target / k_eod / tmax_hour in the distance or as an input.

## Blend (the arm)

```
ridge_pred = predict_int(Ridge band-aware)            # the existing core point forecast
if predicted_risk(day) < c30:        # CALM -> suppress the arm, trust Ridge (calm_day_filter_v0)
    blend = ridge_pred
else:                                 # NON-CALM (ex-ante high-risk)
    w     = W_MAX * clip(analog_conf / CONF_REF, 0, 1)   # confidence-weighted, frozen constants
    blend = round( (1 - w) * ridge_pred + w * analog_pred )
```
Frozen constants (NOT tuned per split): `W_MAX = 0.5`, `CONF_REF = 0.20`, `K = 50`, Laplace `alpha = 1`.
`round` = Q(x) = floor(x+0.5). No per-split tuning; same constants across all splits.

## Protocol

Walk-forward expanding-window, TEST years 2023/2024/2025, operational CP 23:00. Per split: fit Ridge
(per the existing phase3 machinery, per-split train-only climatology), fit the risk logistic (train +
held-out 120d calib), compute c30 + base_rate on train, retrieve analogs from the train pool. Reuse the
existing panel so Ridge and the arm see the SAME rows.

## GATE (GO to promote the arm)

ALL of:
1. On the EX-ANTE non-calm stratum: MAE OR bracket-match improves vs Ridge in >= 2/3 splits.
2. Aggregate (all days) does NOT degrade beyond tolerance: aggregate MAE increase <= 0.02 degC AND
   aggregate bracket-match drop <= 0.005 in every split.
3. RPS (where computed) not worse on the non-calm stratum in >= 2/3 splits.
4. No leakage (guardrails above; pool < test, train-only, no truth in features/gate).
5. Reproducible (deterministic; report regenerates).

## KILL

- Gain only on the truth-derived stratum, not the ex-ante non-calm stratum.
- Improves 1 split, regresses 2.
- Improves high-risk but degrades the aggregate beyond tolerance.
- Needs per-split manual tuning of W_MAX/CONF_REF/K.
- Any future-data / truth-selection leakage.

## Scope (files the implementation may touch)

ALLOWED: `core/models/analog_high_risk.py` (new), `scripts/evaluate_analog_high_risk_arm.py` (new),
`reports/analog/analog_high_risk_arm_v0.{md,json}` (new). Reuse (read-only import) `late_warming_risk`,
`ridge_band`, `training_panel`, `climatology`, `eval/metrics`.
FORBIDDEN: `core/cli/decide.py`, `core/decision/**` (Kelly/EV/sizing/engine), any Polymarket/odds code,
any contract/threshold change, any gate loosening. This is predictor-only.

## What this does NOT do

No execution wiring, no IC/conformal change, no center change to the production forecast path. It is a
gated evaluation of a candidate arm; promotion into the serving path is a separate later step.
