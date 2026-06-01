# T-11-9 Phase 2: Serving Candidate Matrix - Decision Review

Reviewer: Anti winner-shopping / decision review
Date: 2026-06-01
Prereg: contracts/serving_candidate_matrix_v0_prereg.md (v1.0)

> **Update 2026-06-01 (reviewer P2 hygiene):** the matrix was re-run at the production
> `n_estimators=500` (eval == serving) with the ECMWF-window causal-climo override
> (`clim_tmax_c_dec` overwritten with the per-split causal climo, matching the full-window P1 fix).
> Routing decisions are UNCHANGED: CP20-22 -> ECMWF-residual (2/2 folds); CP23 -> Ridge (conservative).
> Only the H2 ECMWF-window point metrics shifted (<= ~0.07 MAE) - H1's causal climo already equalled the
> broad climo, so H1 did not move. The CP23 evidence below (criteria 2 & 3) has been corrected to the
> leak-free full-window logic; the prior wording predated the session-2026-06-01-6 `full_results` patch.
> Authoritative numbers live in `candidate_matrix_v0.{md,json}`.

> **Update 2026-06-01 (reviewer 2nd pass, post-880924f):** corrected three stale-evidence
> lines that survived the hygiene commit - criterion 2 (the `folds_won_by_best=2` gloss now
> distinguishes CP20-22's winner==best_by_mae from CP23's best_by_mae=gfs_residual being
> overridden by the calm gate), criterion 8 (`calm_ok=true` was wrongly stated for "all 4 CPs";
> CP23 is `calm_ok=false`, which is *why* Ridge is kept), and criterion 10 (the script/reports/
> prereg are now committed, not untracked). The PASS 10/10 verdict is unchanged - these were
> documentation-accuracy fixes, not changes to the routing decision.

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
- JSON routing_detail confirms `"folds_won_by_best": 2` at every CP, but the "2" means different
  things by CP: for CP20-22 the winner IS best_by_mae (ecmwf_residual, won 2/2 folds); for CP23 the
  "2" (of 3) describes best_by_mae=gfs_residual, NOT the winner - the winner is ridge, because gfs is
  overridden by the calm gate (calm_ok=false; see the CP23 line below).
- CP20: ECMWF MAE fold1=0.6854 < Ridge 1.0337; fold2=0.5489 < Ridge 0.8207. Wins 2/2.
- CP21: ECMWF MAE fold1=0.6742 < Ridge 0.9382; fold2=0.5435 < Ridge 0.8478. Wins 2/2.
- CP22: ECMWF MAE fold1=0.6742 < Ridge 0.7753; fold2=0.5761 < Ridge 0.7283. Wins 2/2.
- CP23: on the leak-free full 3-fold window, GFS-residual is best_by_mae (pooled 0.6643 vs analog_arm
  0.6660 vs Ridge 0.6770), but GFS degrades the calm stratum (calm_ok=false), so the conservative rule
  keeps Ridge (winner=ridge, folds_won_by_best=2/3). ECMWF/ensemble are not CP23 candidates.

No winner rests on a single fold.

### 3. CP20-22 decided separately from CP23? CP23 kept conservative?

PASS

Evidence:
- scripts/evaluate_serving_candidate_matrix.py:624-625 defines separate candidate lists:
  `candidates_cp20_22 = ["ridge", "gfs_residual", "ecmwf_residual", "ensemble"]`
  `candidates_cp23 = ["ridge", "gfs_residual", "analog_arm"]`
- Line 632: `candidates = candidates_cp23 if is_cp23 else candidates_cp20_22`
- ECMWF-residual and ensemble are EXCLUDED from CP23 candidates entirely.
- CP23 result: Ridge is kept by the conservative rule. On the leak-free full window GFS-residual has the lowest pooled MAE (0.6643) but degrades the calm stratum (calm_ok=false); ECMWF/ensemble are not CP23 candidates at all. Keeping Ridge despite GFS's better pooled MAE is correct conservative behavior.

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
- JSON confirms `"calm_ok": true` for CP20-22, where the recommended ECMWF-residual improves calm
  (data below). CP23 has `"calm_ok": false`, but that flag describes gfs_residual (best_by_mae), which
  degrades calm and is therefore REJECTED; the recommended CP23 model is ridge, which does not degrade
  calm. So the recommended routing (ECMWF-residual @ CP20-22, Ridge @ CP23) degrades calm at no CP -
  which is exactly what this criterion asks.
- Calm stratum data (from report):
  - CP20 fold1: ECMWF calm MAE=0.6164 vs Ridge calm MAE=0.8767 (ECMWF better)
  - CP20 fold2: ECMWF calm MAE=0.5517 vs Ridge calm MAE=0.9483 (ECMWF better)
  - CP21 fold1: ECMWF calm MAE=0.6438 vs Ridge calm MAE=0.8493 (ECMWF better)
  - CP21 fold2: ECMWF calm MAE=0.5000 vs Ridge calm MAE=0.8621 (ECMWF better)
  - CP22 fold1: ECMWF calm MAE=0.6438 vs Ridge calm MAE=0.7671 (ECMWF better)
  - CP22 fold2: ECMWF calm MAE=0.5862 vs Ridge calm MAE=0.7586 (ECMWF better)
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

Evidence (as of commit 880924f; the script/reports/prereg are now COMMITTED, no longer untracked):
- Provenance: matrix script + prereg first committed in c175177, refined in 46445e7, P2-hygiene in
  880924f. The hygiene commit touched only this evaluation's own files (script + `reports/serving/*` +
  governance docs: CHANGELOG, tasks, PROJECT_JOURNEY, PLAN); no foreign code.
- `core/cli/decide.py`: NOT modified.
- `core/decision/`: NOT modified.
- `core/calibration/`: NOT modified.
- No Polymarket, no execution, no contract modifications (the prereg is a NEW frozen contract, not an
  edit to an existing one).

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

Secondary risk (RESOLVED 2026-06-01): the matrix now evaluates at the production
n_estimators=500 (eval == serving); the earlier "200-for-speed" setting is gone. The re-run
confirmed the routing is unchanged, so no production/eval hyperparameter gap remains before wiring.
