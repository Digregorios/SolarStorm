# Preregistration: analog_quality_v0.1 (operationalize the g5 adherence gate)

> `prereg_version = 1.0` (frozen 2026-05-31, before running).

## Context

`analog_retrieval_audit_v0` (Etapa 3): predictive gates g1-g4 PASS 3/3 (incl the focus non-calm
high-risk lift), only g5 (analog_quality) failed. Verified the executed code matches the v0 prereg
distance vector (7 features incl `rain_persistence_path`) - the paste-time omission did NOT affect
the real run. So the open item is ONLY g5: the v0 `analog_quality` = median neighbor distance did
not separate Brier. This prereg replaces that adherence metric WITHOUT touching the retrieval
(same K=50, alpha=1, same 7-feature distance, same anti-leakage guardrails) - i.e. it only changes
how adherence/confidence is MEASURED, not what is predicted.

## New analog_quality definitions (pre-registered, evaluated together)

For each test day's K neighbors (distances d_1..d_K, train-fit standardizer):
```
analog_confidence    = |P_analog - base_rate_train|      (informativeness vs prior)
effective_n          = (sum w)^2 / sum(w^2),  w = exp(-d / s),  s = train-fit median neighbor dist
weighted_mean_dist   = sum(w*d)/sum(w)
```
`high_quality` (per metric) = top-half by that metric on TEST is NOT allowed (leakage); the
high/low cutpoint is the TRAIN self-query median of the SAME metric (fit on train, applied test).

## GATE for g5 (accept the quality metric if, in >= 2/3 splits)

A quality metric q PASSES if the HIGH-q bucket beats the LOW-q bucket on BOTH:
```
g5a Brier(high-q) <= Brier(low-q)
g5b top-decile lift within high-q >= top-decile lift within low-q
```
The chosen analog_quality is the simplest metric that passes (prefer analog_confidence, then
effective_n, then weighted_mean_dist).

## Acceptance

- If any metric passes g5a+g5b in >=2/3 splits -> g5 is operationalized; combined with the v0
  predictive gates (g1-g4 already PASS), the analog high-risk arm is ELIGIBLE for promotion
  (a separate arm-build step, still gated).
- KILL: if no metric passes, analog_quality stays unresolved; analogs remain a strong predictive
  candidate but without a reliable confidence signal -> compare vs NWP (Etapa 4) before building.
- No change to K/alpha/distance features/predictive gates. No forecast wiring.

## Does NOT do

No retrieval change, no center/IC/conformal change, read-only. Only resolves how to measure
analog adherence/confidence.
