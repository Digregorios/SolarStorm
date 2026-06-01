# T-11-6 Anti-Leakage Review: Two-Model Spread Feasibility

Reviewer: Kiro (automated)
Date: 2026-06-01
Prereg: contracts/two_model_spread_feasibility_v0_prereg.md (v1.0)

## Checklist

### 1. Same rows for GFS spread, ECMWF spread, and Ridge error? PASS

Evidence: `scripts/evaluate_two_model_spread_feasibility.py:225-240`

The code iterates over `te_ok` rows, queries both GFS and ECMWF via `select_nwp_v1`,
builds a `valid_mask` (True only when BOTH models return non-null t2m), then applies
that same mask to compute `spread_at_cp`, `y_valid`, `pred_valid`, and `abs_error`.
All arrays are indexed by the same `valid_mask`. Fair comparison.

### 2. Causal selection run_time <= cp-60min for BOTH GFS and ECMWF? PASS

Evidence: `core/ingest/nwp.py:209` (cutoff = cp_utc - safety_margin),
`scripts/evaluate_two_model_spread_feasibility.py:50` (SAFETY_MARGIN = 60min),
`scripts/evaluate_two_model_spread_feasibility.py:207-213` (both calls use same
cp_utc and SAFETY_MARGIN).

`select_nwp_v1` filters `run_time_utc <= cp_utc - 60min` for both models identically.
No future runs can leak.

### 3. Train-only quartile edges + c30 + delta P50? PASS

Evidence:
- Quartile edges: `scripts/evaluate_two_model_spread_feasibility.py:249-258`
  (`_train_quartile_edges` called on `train_spreads` only, applied to test).
- c30: line 276 (`np.quantile(p_tr, 0.30)` where `p_tr` = predictions on train).
- delta_p50: line 280 (`np.median(lw_tr_deltas)` where `lw_tr` = train-only).

Nothing fit on test. Thresholds are frozen from train before test evaluation.

### 4. Ex-ante regime c30 = train P30 (non_calm = top 70%), NOT P70 drift, NOT truth-derived? PASS

Evidence: `scripts/evaluate_two_model_spread_feasibility.py:276`
```
c30 = float(np.quantile(p_tr, 0.30))
```
Then line 298: `non_calm = risk >= c30` (top 70% of predicted risk).

The risk model (`fit_risk_model`) is trained on train data with truth labels, but
`predict_risk` on test uses ONLY pre-CP features (delta_06_to_cp, southerly_at_cp,
rain_persistence_path, month_sin, month_cos) -- see `core/models/late_warming_risk.py:163-170`.
No truth is used at test time. The regime is genuinely ex-ante.

Verified: fold1 c30=0.2431, non_calm n=105/178 (59%); fold2 c30=0.2499, non_calm
n=126/184 (68%). Both consistent with "top 70%" (slight deviation because threshold
is from train, applied to test -- correct behavior).

NOT a P70 drift (T-10-3 bug would use P70 threshold making non_calm = top 30%).

### 5. Within-window walk-forward honestly labelled shorter; train/test disjoint? PASS

Evidence: `scripts/evaluate_two_model_spread_feasibility.py:45-48`
```
SPLITS = [
    ("fold1", 2024-03-01, 2024-12-31, 2025-01-01, 2025-06-30),
    ("fold2", 2024-03-01, 2025-06-30, 2025-07-01, 2025-12-31),
]
```

- Window 2024-03 to 2025-12 (shorter than full 2023-2025, honestly noted in report).
- Fold1: train <= 2024-12-31, test >= 2025-01-01. Disjoint.
- Fold2: train <= 2025-06-30, test >= 2025-07-01. Disjoint.
- Expanding folds (fold2 train includes fold1 train + fold1 test period).
- Report MD line 4: "Window: 2024-03-01 to 2025-12-31 (ECMWF overlap, shorter than 2023-2025)".

### 6. Does FEASIBLE verdict match JSON numbers? PASS (with caveat)

Gate 1: Spearman positive in >= 2 folds.
- Fold1: all 4 CPs positive (0.0482 to 0.1198). Pass.
- Fold2: CP22 (+0.0224), CP23 (+0.1088) positive. Pass.
- Result: 2/2 folds. Gate met.

Gate 2: Q4 > Q1 in >= 2 folds.
- Fold1: CP20 (1.375>1.000), CP21 (1.130>0.885), CP22 (0.881>0.778). Pass.
- Fold2: CP22 (0.758>0.738), CP23 (0.763>0.643). Pass.
- Result: 2/2 folds. Gate met.

Gate 3: CP20-22 majority positive Spearman.
- 4/6 pairs positive (fold1 CP20/21/22 + fold2 CP22). 4 > 3. Gate met.

Gate 4: Causal + same rows + train-only. Met by construction (items 1-3 above).

Verdict FEASIBLE is technically correct per prereg gates. The "marginal, seasonal"
qualifier is honest -- fold2 (winter) shows reversal at CP20-21 with negative
Spearman and Q4<Q1. The signal is real but seasonal.

Caveat: The gate definitions are lenient (any-CP-per-fold). A stricter per-CP
gate would fail at CP20-21 (only 1/2 folds positive each). The prereg does not
require per-CP unanimity, so this is not a violation, but users should note the
signal is concentrated in warm-season fold1.

### 7. Spread is genuine two-model disagreement, not single-model artifact? PASS

Evidence: `scripts/evaluate_two_model_spread_feasibility.py:232-233`
```
spread_at_cp = np.abs(gfs_arr - ecmwf_arr)
```

- `gfs_arr` from `select_nwp_v1(gfs_snaps, ...)` (NCEP_GFS model).
- `ecmwf_arr` from `select_nwp_v1(ecmwf_snaps, ...)` (ECMWF_IFS_HRES model).
- Two independent NWP archives, two independent `read_snapshots` calls (lines 111-118).
- Mean spread values 0.75-1.19 C (non-zero, non-constant).
- Quartile edges show real variation (e.g., fold1 CP20: 0.398/0.722/1.051).

Not a constant, not a single-model artifact.

### 8. Determinism (seed 42)? Reproducible? PASS

Evidence:
- `scripts/evaluate_two_model_spread_feasibility.py:40`: `np.random.seed(SEED)` with SEED=42.
- `fit_risk_model` called with `seed=SEED` (line 274).
- No other randomness (no shuffle, no sampling).
- JSON reports `"seed": 42, "deterministic": true`.
- All operations are deterministic given fixed data (Spearman, percentiles, Ridge with fixed alpha grid).

### 9. Forbidden files untouched? PASS

`git status --short` output:
```
 M references/code-reviews/update.txt
?? artifacts/
?? contracts/two_model_spread_feasibility_v0_prereg.md
?? reports/calibration/two_model_spread_feasibility.json
?? reports/calibration/two_model_spread_feasibility.md
?? scripts/evaluate_two_model_spread_feasibility.py
```

`git diff --stat`: only `references/code-reviews/update.txt` modified (104 ins, 25 del).

Forbidden files NOT touched:
- core/cli/decide.py: not in git status. Clean.
- core/decision/**: not in git status. Clean.
- Polymarket/odds/execution: not in git status. Clean.
- No calibrator built. No calibration files modified.
- Only the prereg contract created (allowed per prereg scope).

The `update.txt` modification is a planning/routing document, not a forbidden file.

### 10. Winner-shopping across spread candidates? PASS

Evidence: Only ONE spread candidate was evaluated: `spread_at_cp = |GFS_t2m - ECMWF_t2m|`.
The prereg lists multiple candidates (maxtraj spread, std), but the code explicitly
notes (line 243-247) that maxtraj_spread from the single-model panel would be zero,
so only the primary candidate is used. No multiple-comparison issue.

No cherry-picking across candidates. No need for multiple-comparison caveat.

---

## Overall Verdict

**PASS: Faithful + leak-free.**

The FEASIBLE conclusion is honest given the prereg gate definitions. The signal is
marginal and seasonal (strong in warm-season fold1, reversed in winter fold2), and
the report transparently discloses this. All anti-leakage requirements are met:

- Causal NWP selection (run_time <= cp - 60min) for both models.
- Same rows for spread and error.
- Train-only thresholds (quartile edges, c30, delta_p50).
- Ex-ante regime (predicted risk, not truth-derived).
- Disjoint train/test splits.
- Genuine two-model disagreement (not constant, not single-model).
- Deterministic and reproducible.
- No forbidden files touched.
- No winner-shopping.

No leakage, no P70 drift, no unfair comparison detected.
