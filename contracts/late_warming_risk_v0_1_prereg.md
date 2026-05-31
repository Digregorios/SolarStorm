# Preregistration: material_late_warming_risk_model_v0.1

> `prereg_version = 1.0` (frozen 2026-05-31, before running).
>
> Frozen 2026-05-31 BEFORE running. Per `references/code-reviews/update.txt`: v0 failed its
> acceptance gate on top-decile SHARPNESS (lift@10% >= 1.4, passed only 1/3 splits) but showed
> robust OOS BUCKET separation. The intended use of this component is a low/mid/high risk
> bucketizer (to later condition conformal / upper-tail), NOT a top-10% hunter. So v0.1 re-gates
> on bucket separation - the capability that matches the use - WITHOUT relaxing the v0 gate
> retroactively (v0 stays GO=False, diagnostic-only).

## Status of v0 (unchanged)

`risk_model_v0`: diagnostic only, `accepted_for_forecast = false`. The 1.4 top-decile gate is NOT
loosened. This is a SEPARATE, newly pre-registered evaluation with its own gate.

## Target (audit-only, single)

`material_late_warming = (k_eod - k_cp >= 2)` at operational CP 23:00 UTC. Base rate ~0.377.

## Variants (pre-registered)

- **v0.1a**: same model as v0 - logistic on `delta_06_to_cp, southerly_at_cp,
  rain_persistence_path, month_sin, month_cos`, isotonic held-out calibration.
- **v0.1b**: v0.1a + `s_to_n` (overnight modal S -> CP modal N) as ONE extra feature, under the
  SAME L2 logistic (C=1.0) so the rare high-lift small-n signal is shrunk, not trusted raw. No
  GBM in v0.1 (first establish whether the gate, not the model class, was the issue).

## Buckets (frozen): by TRAIN risk quantile (Option B)

To guarantee non-empty buckets and measure separation honestly, buckets are defined by the
predicted-risk quantiles fit ON TRAIN and applied on TEST:
```
low  = predicted risk in bottom 30% (train-fit cutpoint)
mid  = middle 40%
high = top 30%
```

## Split protocol (unchanged from v0)

Walk-forward test years 2023/2024/2025; within each, fit on train before the last 120 d, isotonic
calibrate on the held-out 120 d, evaluate on the test year. Bucket cutpoints fit on the
train-fit predicted risks, applied to test. Test never seen in fit/calib/cutpoint selection.

## GATE (pre-registered; accept v0.1 if ALL hold in >= 2/3 splits)

```
g1 Brier < base-rate Brier
g2 PR-AUC > base rate
g3 high-bucket obs-rate >= 1.35x base
g4 low-bucket  obs-rate <= 0.80x base
g5 (high-bucket obs-rate) - (low-bucket obs-rate) >= 0.25 absolute
g6 monotone low <= mid <= high
g7 n_high >= 25 and n_low >= 25 per split
g8 no post-CP timestamps (enforced by build_features ts<cp + unit test)
```
Rationale: g3-g6 measure the bucketizer capability that the downstream use needs; top-decile
sharpness is intentionally NOT a gate here (it was the v0 mismatch).

## Acceptance / kill

- ACCEPT v0.1 (a or b) if all gates hold >= 2/3 splits. If both pass, prefer **v0.1a** (simpler;
  s_to_n only earns its place if v0.1b clearly beats a on g3/g5).
- KILL / no-go: if neither variant passes, the risk model stays diagnostic; do NOT proceed to
  conditional conformal. Do NOT add GBM or tune thresholds to force a pass (open a v0.2 prereg).
- No threshold/feature/seed re-tuning after seeing results.

## What v0.1 does NOT do

No center (p50) change; no conditional conformal here; s_to_n stays shrunk (no raw rare-event
feature). Output remains diagnostic (prob + risk_bucket) until a variant passes this gate.
