# T-11-6 Decision Diagnosis: Two-Model Spread

Task: T-11-6 two_model_spread_feasibility
Prereg: contracts/two_model_spread_feasibility_v0_prereg.md v1.0
Date: 2026-06-01

## Verdict

**(a) CALIBRATION only** -- the two-model spread is a candidate difficulty axis
for a future integer-native/CQR calibrator (T-11-8). It is NOT suitable for
point routing.

## Evidence

### 1. Per-CP Spearman is seasonal and weak

| CP    | Fold1  | Fold2   |
|-------|--------|---------|
| 20:00 | +0.119 | -0.085  |
| 21:00 | +0.064 | -0.079  |
| 22:00 | +0.120 | +0.022  |
| 23:00 | +0.048 | +0.109  |

Fold1 (summer/autumn) shows positive correlation at CP20-22 (rho 0.06-0.12).
Fold2 (winter-dominated) reverses at CP20-21 and is near-zero at CP22.
No single CP has a consistent, strong positive signal across both folds.

### 2. Q1->Q4 error curve: monotonic only in fold1 CP20-21

- CP20 fold1: Q1=1.00, Q4=1.38 (strong +38% rise). Fold2: Q4 < Q1 (reversed).
- CP21 fold1: Q1=0.88, Q4=1.13 (+28%). Fold2: Q4 < Q1 (reversed).
- CP22 fold1: Q1=0.78, Q4=0.88 (+13%). Fold2: Q4 > Q1 (+3%, negligible).
- CP23: non-monotonic in both folds.

The Q4>Q1 pattern that justifies "high spread = hard day" holds reliably only
in the warm season at CP20-22.

### 3. Strata concentration (non_calm / high_delta_06)

Fold1 CP20-22 non_calm: rho = 0.15, 0.16, 0.18 (strongest signal).
Fold1 CP20 high_delta_06: rho = 0.19 (peak).
Fold2 same strata: rho = -0.14 to -0.22 (REVERSED).

The signal concentrates exactly where the prereg predicted (CP20-22, non_calm,
high_delta) but ONLY in the warm season. In winter the same strata show the
spread is anti-correlated with error -- high spread days are EASIER, not harder.

### 4. Why NOT point routing (option b)

Point routing requires a CONSISTENT conditional signal: "when spread > X, pick
model A over model B." The data shows:
- The spread-error relationship flips sign between seasons.
- No CP has a stable positive Spearman across both folds.
- A router conditioned on spread would make correct calls in summer and
  WRONG calls in winter, with no ex-ante way to know which regime applies
  (the fold split is temporal, not regime-labeled).

A routing rule that works half the year and hurts the other half is not
actionable without an additional seasonal gate -- which adds complexity and
was not tested here.

### 5. Why CALIBRATION is still viable (option a)

A CQR/integer-native calibrator (T-11-8) can use spread as ONE difficulty
feature among several, with the model free to learn the seasonal interaction.
The key facts supporting this:
- The signal IS real in the warm season (rho up to 0.19, Q4/Q1 ratio 1.38).
- It concentrates at CP20-22 where calibration value is highest.
- It is causal and available at decision time.
- A calibrator with seasonal features (month, delta_06) can learn WHEN spread
  matters and WHEN to ignore it, unlike a hard routing rule.

### 6. Honest caveats

- Window is short (2024-03 to 2025-12, ~22 months, n=178/184 per fold).
- No Spearman p-value is below 0.05 (best: p=0.111 at CP22 fold1).
- The seasonal reversal means spread alone is NOT a universal difficulty axis;
  it must be interacted with season/regime features.
- REQ-AUD-5 gate still applies unchanged to any future calibrator that
  consumes this signal. This diagnosis does not reopen that gate.

## Recommendation

Use the two-model spread as a CANDIDATE FEATURE (difficulty axis) for the
T-11-8 integer-native/CQR calibrator, interacted with seasonal indicators.
Do NOT use it for unconditional point routing. The signal is real but seasonal
and weak in isolation; a learned model can exploit it where it helps and
suppress it where it reverses.

If T-11-8 calibrator does not improve on the current Ridge baseline after
incorporating spread (per REQ-AUD-5), the spread feature should be dropped.
No auto-reopen of calibration gates from this diagnosis alone.
