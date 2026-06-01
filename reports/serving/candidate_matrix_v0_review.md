# T-11-9 Phase 2: Serving Candidate Matrix - Decision Review

Reviewer: Anti winner-shopping / decision review
Date: 2026-06-01
Prereg: contracts/serving_candidate_matrix_v0_prereg.md (v1.0)

## Checklist

### 1. Same rows per slice? Window differences honestly labelled?

PASS

Evidence:
- scripts/evaluate_serving_candidate_matrix.py:227 computes `common_dates = sorted(set(...) & set(...) & set(...) & set(...))` for the ECMWF window, intersecting base/GFS/ECMWF/ensemble test dates.
- scripts/evaluate_serving_candidate_matrix.py:528 does the same for the full window (base & GFS).
- All candidates within a split are evaluated on the SAME `common_dates` rows (lines 235-240 filter each panel to `common_dates`).
- The report (candidate_matrix_v0.md) explicitly labels "ECMWF overlap 2024-03..2025-12 (2 folds)" vs "Full 2023-2025 (3 folds)" and warns "Do NOT directly compare a 3-fold metric here against a 2-fold ECMWF metric."
- JSON confirms `"window": "ecmwf_overlap"` vs `"window": "full_2023_2025"` per split.
- n_test is identical across all candidates within each CP/split (178 in fold 1, 184 in fold 2).

### 2. Winner-shopping: does any winner rest on a single lucky fold?

PASS

Evidence:
- scripts/evaluate_serving_candidate_matrix.py:652 sets `need_folds = min(2, n_folds)` (= 2 for the 2-fold ECMWF window).
- Line 695: `elif folds_won < need_folds:` rejects any candidate that does not win in >= 2 folds.
- JSON routing_detail confirms `"folds_won_by_best": 2` for all 4 CPs.
- CP20: ECMWF MAE fold1=0.6854 < Ridge 1.0337; fold2=0.5543 < Ridge 0.7989. Wins 2/2.
- CP21: ECMWF MAE fold1=0.6742 < Ridge 0.9382; fold2=0.5435 < Ridge 0.8152. Wins 2/2.
- CP22: ECMWF MAE fold1=0.6742 < Ridge 0.7753; fold2=0.5707 < Ridge 0.7283. Wins 2/2.
- CP23: Ridge is best_by_mae (pooled 0.6714 vs analog 0.6824 vs GFS 0.7456). Wins 2/2 as incumbent.

No winner rests on a single fold.

### 3. CP20-22 decided separately from CP23? CP23 kept conservative?

PASS

Evidence:
- scripts/evaluate_serving_candidate_matrix.py:624-625 defines separate candidate lists:
  `candidates_cp20_22 = ["ridge", "gfs_residual", "ecmwf_residual", "ensemble"]`
  `candidates_cp23 = ["ridge", "gfs_residual", "analog_arm"]`
- Line 632: `candidates = candidates_cp23 if is_cp23 else candidates_cp20_22`
- ECMWF-residual and ensemble are EXCLUDED from CP23 candidates entirely.
- CP23 result: Ridge wins (pooled MAE 0.6714), not switched to ECMWF despite ECMWF being close in fold 2 (0.5761). This is correct conservative behavior.

### 4. |GFS-ECMWF| spread EXCLUDED from routing?

PASS

Evidence:
- grep of the entire script for "spread|GFS.*ECMWF.*diff|abs(.*gfs.*ecmwf" returns only declaration strings (lines 749, 780, 804) stating spread is excluded.
- No computation of |GFS-ECMWF| difference anywhere in the routing logic.
- No spread variable used in `compute_routing_recommendation()`.
- JSON: `"spread_excluded": true`.

### 5. Ex-ante regime canonical c30=P30 (NOT P70, NOT truth)?

PASS

Evidence:
- scripts/evaluate_serving_candidate_matrix.py:416: `c30 = float(np.percentile(p_train, 30))`
- This is the 30th percentile of predicted risk on TRAINING data only (line 414: `p_train = predict_risk(risk_model, risk_train)`).
- Line 425-426: `non_calm: predicted risk >= c30 (top 70% = non_calm; bottom 30% = calm)` - correct semantics.
- Risk model is fit on train only (line 414: `risk_model = fit_risk_model(risk_train, seed=SEED)`).
- Threshold applied to test predictions (line 419-422: `p_test = predict_risk(risk_model, risk_test)`).
- No P70 drift. No truth-based regime assignment.

### 6. Causal NWP (run_time <= cp-60min) both models; train-only climatology/thresholds?

PASS

Evidence:
- NWP causality enforced upstream: core/ingest/nwp.py:32 defines `SAFETY_MARGIN_DEFAULT = timedelta(minutes=60)`. Line 217: `cutoff = cp_utc - safety_margin`. Line 205: "Filters runs with run_time_utc <= cp_utc - safety_margin".
- core/features/training_panel.py:6 states "Causality is enforced upstream by build_cp_features (REQ-CON-5, REQ-AUD-4)". Line 151: `target_valid_utc=f.cp_utc` (causal at CP).
- Train-only climatology: scripts/evaluate_serving_candidate_matrix.py:244-247 and 538-541 both filter labels to `<= tr_end` before fitting climatology.
- Train-only risk thresholds: line 405-406 filters risk_df to train period; line 414 fits risk model on train only.

### 7. Ensemble appears ONLY as per-CP candidate, NOT promoted at CP23?

PASS

Evidence:
- scripts/evaluate_serving_candidate_matrix.py:624: ensemble is in `candidates_cp20_22` only.
- Line 625: `candidates_cp23 = ["ridge", "gfs_residual", "analog_arm"]` - ensemble absent.
- Ensemble metrics ARE computed and reported at CP23 in the head-to-head matrix (for transparency), but the routing logic never considers it for CP23.
- Report notes: "Ensemble is a per-CP candidate only, NOT a global default (T-11-5 showed it regresses CP23)."

### 8. Calm/stable days not degraded by recommended routing?

PASS

Evidence:
- scripts/evaluate_serving_candidate_matrix.py:685-688 checks calm degradation with 0.05 tolerance.
- JSON confirms `"calm_ok": true` for all 4 CPs.
- Calm stratum data (from report):
  - CP20 fold1: ECMWF calm MAE=0.6164 vs Ridge calm MAE=0.8767 (ECMWF better)
  - CP20 fold2: ECMWF calm MAE=0.5172 vs Ridge calm MAE=0.8793 (ECMWF better)
  - CP21 fold1: ECMWF calm MAE=0.6438 vs Ridge calm MAE=0.8493 (ECMWF better)
  - CP21 fold2: ECMWF calm MAE=0.4828 vs Ridge calm MAE=0.8103 (ECMWF better)
  - CP22 fold1: ECMWF calm MAE=0.6438 vs Ridge calm MAE=0.7671 (ECMWF better)
  - CP22 fold2: ECMWF calm MAE=0.5862 vs Ridge calm MAE=0.7414 (ECMWF better)
- ECMWF-residual improves calm days at all CP20-22 in both folds. No degradation.

### 9. Determinism (seed 42)? Reproducible?

PASS

Evidence:
- scripts/evaluate_serving_candidate_matrix.py:57-58: `SEED = 42; np.random.seed(SEED)`
- Line 374: `fit_analog_arm(..., seed=SEED)`
- Line 414: `fit_risk_model(risk_train, seed=SEED)`
- JSON: `"seed": 42, "deterministic": true, "num_threads": 1`
- num_threads=1 prevents non-deterministic thread ordering in LGBM.

### 10. Forbidden files untouched?

PASS

Evidence (git status --short + git diff --stat):
- Modified: `references/code-reviews/update.txt` only (unrelated, 15 ins / 25 del).
- Untracked (new, expected): `contracts/serving_candidate_matrix_v0_prereg.md`, `reports/serving/`, `scripts/evaluate_serving_candidate_matrix.py`.
- `core/cli/decide.py`: NOT modified (git status --short returns empty).
- `core/decision/`: NOT modified (git status --short returns empty).
- `core/calibration/`: NOT modified (git status --short returns empty).
- No Polymarket, no execution, no contract changes (only the new prereg is untracked).

## Verdict

**PASS.** The serving candidate matrix is a fair, leak-free, non-winner-shopped basis
for a conservative recommended routing.

All 10 criteria satisfied:
- Same rows enforced via date intersection per split
- Window differences honestly labelled (2-fold ECMWF vs 3-fold full)
- No winner rests on a single fold (all win 2/2)
- CP20-22 rigidly separated from CP23
- CP23 conservative (ECMWF/ensemble excluded from candidate set)
- No spread-based routing
- Ex-ante regime c30=P30 on train-only predictions
- Causal NWP (60min safety margin)
- Train-only climatology and thresholds
- Calm days improved (not degraded) by recommended routing
- Deterministic (seed 42, num_threads=1)
- No forbidden files touched

## Single Biggest Risk for Phase 3 Serving

**ECMWF data availability at inference time.** The ECMWF-residual recommendation for
CP20-22 depends on timely ECMWF IFS HRES data being available with run_time <= CP-60min.
If ECMWF data is delayed or missing at serving time, the system needs a fallback path
(likely Ridge or GFS-residual). The evaluation assumes ECMWF data is always present
(rows without it are excluded via the common-date intersection). Phase 3 must implement
a graceful degradation path for missing ECMWF runs, or the CP20-22 improvement will be
unreliable in production.

Secondary risk: the evaluation uses n_estimators=200 (reduced from 500 for speed). If
Phase 3 deploys with 500, the model behavior may differ slightly from what was evaluated
here. Recommend re-running with production hyperparameters before final wiring.
