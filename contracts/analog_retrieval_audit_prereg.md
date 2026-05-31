# Preregistration: analog_retrieval_audit (Etapa 3)

> `prereg_version = 1.0` (frozen 2026-05-31, before running).

## Objective

Test whether CAUSAL analogs capture the HIGH-risk material late-warming days that the simple
logistic could not (`risk_model` GO=False as a high-risk detector). Question: do historically
similar days (up to the CP) have an informative `P(material_late_warming = k_eod-k_cp>=2)`,
ESPECIALLY on non-calm days? The calm side is already covered by `calm_day_filter_v0` (GO=True);
analogs are evaluated primarily where `calm_day_filter = false`.

## Anti-leakage guardrails (MANDATORY - analogs are where causality breaks silently)

```
analog_pool_date < forecast_date            (no future neighbors, stricter than ts<cp)
analog pool within the TRAIN split only      (test day never retrieves test/calib neighbors)
all distance features use ts_utc < cp_utc
NEVER use k_eod / remaining_after_cp / tmax_hour / target as a distance input
distance scaling (means/stds) fit on TRAIN only
```

## Distance feature vector (small, v0 - NOT 30 features)

Reuse already-built causal features (from late_warming_risk.build_features + a couple extras):
```
thermal:  k_cp, delta_06_to_cp
regime:   southerly_at_cp, rain_persistence_path
wind:     s_to_n
season:   month_sin, month_cos
```
Standardized (train means/stds). Euclidean distance; K = 50 nearest train-pool neighbors.

## Analog distribution

`P_analog(material_lw) = smoothed frequency among the K neighbors`:
`(count_lw + alpha) / (K + 2*alpha)`, alpha = 1. `analog_quality` = high/low by median neighbor
distance (train-fit median split).

## Split protocol

Walk-forward 2023/2024/2025. For each test day, neighbors are drawn ONLY from train-split days
with date < that test day's year start (the whole train block, all < test). Standardizer + the
analog_quality distance cutpoint fit on train. Test never in the pool.

## GATE (accept if all hold in >= 2/3 splits)

```
1. Brier(P_analog) < base-rate Brier
2. PR-AUC(P_analog) > base rate
3. top-decile lift >= 1.4
4. on NON-CALM days (calm_day_filter=false): high-risk lift >= 1.25
5. high analog_quality bucket outperforms low (Brier or lift)
6. no leakage (guardrails above; pool strictly < forecast date, train-only)
```

## Acceptance / kill

ACCEPT if all gates hold >= 2/3. Then analogs become a candidate HIGH-risk arm (upper-tail).
KILL/no-go: if analogs do not pass the high-risk side, the next candidate is NWP / Open-Meteo
multi-model (Etapa 4). Do NOT expand to 30 features or tune K/alpha to force a pass (open a v0.2).

## What this does NOT do

Read-only audit. No center change, no IC change, no conditional conformal, no forecast wiring.
Diagnostic verdict only: "can analogs capture the high-risk side?".
