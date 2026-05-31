# Anti-Leakage Review: analog_high_risk_arm_v0 (T-9-1)

Reviewer: Kiro (automated anti-leakage reviewer)
Date: 2026-05-31
Prereg: contracts/analog_high_risk_arm_v0_prereg.md (frozen v1.0)

## Checklist

### 1. OPERATIONAL GATE IS EX-ANTE/CAUSAL (MOST CRITICAL)

**PASS**

Evidence:
- `core/models/analog_high_risk.py:120-127`: The gate is `p_risk < state.c30` where
  `p_risk = predict_risk(state.risk_model, risk_df)`. The risk model uses only
  FEATURE_NAMES = ("delta_06_to_cp", "southerly_at_cp", "rain_persistence_path",
  "month_sin", "month_cos") -- all pre-CP features (late_warming_risk.py:33).
- `core/models/analog_high_risk.py:80`: c30 = 30th percentile of TRAIN predicted risk.
- The truth-derived stratum ("lw_truth_DIAGNOSTIC") is reported for insight only
  (scripts/evaluate_analog_high_risk_arm.py:170) and never used in the GO gate
  (scripts/evaluate_analog_high_risk_arm.py:195-200 uses "noncalm" stratum).
- The gate does NOT use actual late-warming outcome. It is fully ex-ante.

### 2. ANALOG POOL STRICTLY date < test day; POOL IS TRAIN-ONLY

**PASS**

Evidence:
- `scripts/evaluate_analog_high_risk_arm.py:106-107`: Pool is filtered to
  `date_local >= train_start AND date_local <= train_end`.
- `core/eval/cv.py:42`: `train_end = test_start - timedelta(days=1)`.
- Therefore ALL pool days are strictly before ALL test days by construction.
- No test or calib-period days outside train_end enter the pool.
- `predict_analog_batch` (analog_high_risk.py:155-180) retrieves from the full
  pool without per-day date filtering, but this is safe because the pool is
  already bounded to < test_start.

### 3. STANDARDIZER / c30 / base_rate FIT ON TRAIN ONLY

**PASS**

Evidence:
- `core/models/analog_high_risk.py:85-90`: feat_mean, feat_std computed on
  `risk_df` which is `risk_train_all_with_tmax` (train-only).
- `core/models/analog_high_risk.py:78-80`: c30 computed from `predict_risk` on
  `risk_df` (train-only).
- `core/models/analog_high_risk.py:82-83`: base_rate_train = mean of train targets.
- `fit_risk_model` (late_warming_risk.py:142-165): logistic fit on train; isotonic
  on held-out calib (last 120d of train). Both are train-period data.
- No test data enters any of these computations.

### 4. TARGET / k_eod / tmax_hour ABSENT FROM DISTANCE VECTOR AND analog_pred INPUT

**PASS**

Evidence:
- `core/models/analog_high_risk.py:44-52`: ANALOG_FEATURES = ("k_cp",
  "delta_06_to_cp", "southerly_at_cp", "rain_persistence_path", "s_to_n",
  "month_sin", "month_cos"). No target, k_eod, or tmax_hour.
- grep for "k_eod|tmax_hour|target_tmax" in analog_high_risk.py: zero matches.
- `analog_pred = k_cp_test + analog_delta` (line 145/173): uses only k_cp (pre-CP
  max) and the mean delta from TRAINING neighbors.
- The `pool_tmax_int` used for neighbor deltas is the TRAINING days' actual tmax
  (historical truth, causally available). This is correct.

### 5. NO ACCIDENTAL TRUTH-SELECTION

**PASS**

Evidence:
- The arm acts on days where `predicted_risk >= c30` (ex-ante gate). The truth
  label is never used to decide where the arm acts.
- Neighbor selection is by Euclidean distance on the 7 causal features only
  (analog_high_risk.py:136-139 / 166-169). No truth-based filtering of neighbors.
- The `pool_target` (binary late-warming indicator of TRAINING neighbors) is used
  only to compute `p_analog` for the confidence weight -- this is historical
  outcome data, not test-day truth.
- The diagnostic truth stratum ("lw_truth_DIAGNOSTIC") is computed and reported
  but never feeds into the GO gate logic (evaluate script lines 195-200).

### 6. REPORTED GAIN ON EX-ANTE NON-CALM STRATUM IN >= 2/3 SPLITS

**PASS**

Evidence (from analog_high_risk_arm_v0.json):
- 2023 noncalm: Ridge MAE=0.7273 -> Arm MAE=0.7037 (improved); BM 0.4343->0.4478 (improved)
- 2024 noncalm: Ridge MAE=0.7180 -> Arm MAE=0.7035 (improved); BM 0.4593->0.4767 (improved)
- 2025 noncalm: Ridge MAE=0.7000 -> Arm MAE=0.6929 (improved); BM 0.4071->0.4071 (tied)
- MAE improves in 3/3 splits. BM improves in 2/3 splits (tied in 2025).
- Gate G1 requires MAE OR BM improvement in >= 2/3 splits: satisfied (3/3 by MAE).
- Gain is NOT only on the truth-derived stratum; it exists on the ex-ante stratum.

### 7. AGGREGATE DOES NOT DEGRADE BEYOND TOLERANCE

**PASS**

Evidence (from analog_high_risk_arm_v0.json, "all" stratum):
- 2023: MAE delta = 0.7178 - 0.737 = -0.0192 (improvement); BM delta = +0.0109 (improvement)
- 2024: MAE delta = 0.6932 - 0.7068 = -0.0136 (improvement); BM delta = +0.0164 (improvement)
- 2025: MAE delta = 0.6521 - 0.6575 = -0.0054 (improvement); BM delta = 0.0 (tied)
- All splits show improvement or no change. Well within tolerance (MAE +<=0.02, BM drop <=0.005).

### 8. RIDGE AND ARM USE THE SAME PANEL/ROWS

**PASS**

Evidence:
- `scripts/evaluate_analog_high_risk_arm.py:77-78`: Both use `test` (same panel
  filter on date range and CP).
- `scripts/evaluate_analog_high_risk_arm.py:140`: `arm_preds = np.copy(ridge_preds)`
  -- starts from Ridge, overwrites only where risk features exist.
- Metrics computed on same `y_test_int` array (line 101).
- Calm stratum confirms identity: Ridge == Arm on all calm metrics in all 3 splits.

### 9. NO PER-SPLIT TUNING OR OVERFIT

**PASS**

Evidence:
- `core/models/analog_high_risk.py:30-34`: Constants are module-level:
  W_MAX=0.5, CONF_REF=0.20, K_NEIGHBORS=50, LAPLACE_ALPHA=1, SEED=42.
- grep for these constants in the evaluation script: zero matches (never overridden).
- No conditional logic per split name or year in either file.
- Constants match the prereg exactly.

### 10. NO FORBIDDEN FILES TOUCHED

**PASS**

Evidence (`git status --short` + `git diff --stat`):
- Modified: `references/code-reviews/update.txt` (documentation notes, not forbidden)
- New untracked: `contracts/analog_high_risk_arm_v0_prereg.md` (the prereg itself),
  `core/models/analog_high_risk.py`, `scripts/evaluate_analog_high_risk_arm.py`,
  `reports/analog/analog_high_risk_arm_v0.{json,md}` -- all ALLOWED per prereg scope.
- Untracked dirs `artifacts/`, `projetos_github/`, `quarentena/` are not forbidden files.
- No changes to: core/cli/decide.py, core/decision/**, Polymarket/odds, contracts
  (other than the prereg), gate thresholds.

## Minor Observations (non-blocking)

1. The `predict_analog` (single-row) function at line 143 uses
   `(neighbor_deltas.sum() + LAPLACE_ALPHA * 0.0) / (k + LAPLACE_ALPHA)` while
   `predict_analog_batch` at line 171 uses `neighbor_deltas.sum() / (k + LAPLACE_ALPHA)`.
   These are mathematically equivalent (adding 0), but the inconsistency is cosmetic.

2. The 2024 split has 94.2% non-calm days (only 21 calm). This is because c30=0.3137
   is relatively low and the 2024 test year may have higher predicted risk. Not a bug
   -- the gate is correctly applied ex-ante -- but worth noting that the "calm"
   stratum is very small in that split.

3. Gate G3 (RPS) is marked PASS with note "point-forecast arm; RPS not computed".
   The prereg says "RPS (where computed) not worse" -- since this arm only produces
   point forecasts and does not modify the probability distribution, this is a
   reasonable interpretation. No RPS degradation is possible from a point-forecast-only
   arm that does not touch the conformal/IC machinery.

## OVERALL VERDICT

**PASS -- Implementation is leak-free and faithfully realizes the prereg.**

The GO conclusion is honest and supported:
- The gain exists on the EX-ANTE non-calm stratum (not only the truth-derived diagnostic).
- MAE improves in 3/3 splits on the operational stratum.
- Aggregate improves or holds in all splits (well within tolerance).
- No future data, no truth-selection, no per-split tuning.
- Constants are frozen and match the prereg exactly.
- The causal gate uses only CP-available features.
- The analog pool is strictly train-only and date < test.

The GO verdict is warranted.
