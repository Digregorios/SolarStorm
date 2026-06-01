# T-11-5 Anti-Leakage Review: ECMWF Ensemble Point Gain

Reviewer: T-11-5 anti-leakage reviewer
Date: 2026-06-01
Prereg: contracts/ecmwf_ensemble_point_gain_v0_prereg.md (v1.0)

## Overall Verdict: CONDITIONAL FAIL (Gate 2 logic bug produces incorrect KILL)

The implementation is leak-free and methodologically sound, but the Gate 2
logic is overly strict: it fails the entire evaluation when the ENSEMBLE
regresses CP23, even though ECMWF-residual alone passes all 5 gates. The
prereg explicitly says "GO = the simplest candidate (prefer ECMWF-residual,
then ensemble) meeting 1-4", meaning gates should be evaluated per-candidate.
The KILL verdict is therefore INCORRECT per the prereg's own language.

---

## Checklist

### 1. Same test rows per split (fair comparison)
**PASS**

Evidence: `scripts/evaluate_ecmwf_ensemble_point_gain.py:215-222`

```
dates_base = set(te_base["date_local"].to_list())
dates_gfs = set(te_gfs_ok["date_local"].to_list())
dates_ecmwf = set(te_ecmwf_ok["date_local"].to_list())
dates_ens = set(te_ens_ok["date_local"].to_list())
common_dates = sorted(dates_base & dates_gfs & dates_ecmwf & dates_ens)
```

All 4 candidates are evaluated on the intersection of available dates.
JSON confirms n=178 (H1) and n=184 (H2) for all candidates at each CP.

### 2. Causal NWP: run_time <= cp - safety_margin for BOTH GFS and ECMWF
**PASS**

Evidence:
- `core/ingest/nwp.py:32`: `SAFETY_MARGIN_DEFAULT = timedelta(minutes=60)`
- `core/ingest/nwp.py:211`: `cutoff = cp_utc - safety_margin`
- `core/ingest/nwp.py:212`: `causal = snapshots.filter(pl.col("run_time_utc") <= cutoff)`
- `core/features/nwp.py:78,169`: both `compute_nwp_features` and
  `select_max_trajectory_anchor` pass `safety_margin=SAFETY_MARGIN_DEFAULT`
- `core/ingest/nwp.py:245-258`: `select_nwp_ensemble` applies `select_nwp_v1`
  per model, so both GFS and ECMWF get the same causal filter.

The 60-minute safety margin matches the prereg's "run_time <= cp - 60min".

### 3. Per-split train-only climatology + c30 + delta P50 - nothing fit on test
**PASS**

Evidence: `scripts/evaluate_ecmwf_ensemble_point_gain.py:230-236`

```
climo = fit_climatology(climo_labels, train_start=date(2020, 1, 1), train_end=tr_end)
```

c30 computed from train risk predictions only (line 298):
```
p_tr = predict_risk(risk_model, lw_tr)
c30 = float(np.quantile(p_tr, 0.30))
```

delta_p50 from train only (line 316):
```
lw_tr_deltas = [r["delta_06_to_cp"] for r in lw_tr.iter_rows(named=True) ...]
delta_p50 = float(np.median(lw_tr_deltas))
```

No test data leaks into any threshold or model fit.

### 4. Non_calm regime EX-ANTE (predicted risk vs train c30), not truth-derived; c30 = canonical P30
**PASS**

Evidence: `scripts/evaluate_ecmwf_ensemble_point_gain.py:290-300`

- Risk model fit on TRAIN only (`fit_risk_model(lw_tr, seed=SEED)`)
- c30 = `np.quantile(p_tr, 0.30)` = 30th percentile of train predicted risk
- non_calm = `risk_map.get(d, 0.0) >= c30` (risk >= P30 = top 70%)
- This matches T-9-1/T-9-3/T-10-3: calm = bottom 30% risk, non_calm = top 70%

NO P70 drift. The definition is: calm = risk < c30 (bottom 30%), non_calm =
risk >= c30 (top 70%). Confirmed consistent with:
- `reports/model_error_taxonomy.md:54`: "calm = bottom-30% predicted risk;
  non_calm = risk >= train P30"
- `reports/spike/calm_day_filter_v0.md:3`: "calm rule: predicted_risk < train P30"

The `high_delta_06` feature (`delta_06_to_cp`) is a pre-CP observable (morning
thermal momentum), not truth-derived. Threshold from train P50.

### 5. Walk-forward honestly labelled as shorter; train/test disjoint
**PASS**

Evidence:
- Report header: "SHORTER than 2023-2025 point splits"
- `scripts/evaluate_ecmwf_ensemble_point_gain.py:47-50`:
  Split 1: train 2024-03-01..2024-12-31, test 2025-01-01..2025-06-30
  Split 2: train 2024-03-01..2025-06-30, test 2025-07-01..2025-12-31
- Train and test date ranges are strictly disjoint (no overlap).
- Only 2 splits (>= 2 required by prereg). Honestly noted.

### 6. GO/KILL gate matches prereg
**FAIL - Gate 2 logic bug**

The prereg states (Gate section):
> "GO = the simplest candidate (prefer ECMWF-residual, then ensemble) meeting 1-4."

This means gates should be evaluated PER-CANDIDATE. The code at line 404:
```
for cand_m in [ecmwf_m, ens_m]:
    if cand_m["mae"] - best_existing_mae > 0.02:
        gate2 = False
```

This fails gate2 globally if ANY candidate regresses, even if the preferred
candidate (ECMWF-res) passes. From the JSON:

- Split 2025-H1 CP23: Ridge MAE=0.6742, GFS-res MAE=0.8989
  - ECMWF-res MAE=0.6798: regression = +0.0056 (WITHIN 0.02 tolerance)
  - Ensemble MAE=0.8258: regression = +0.1516 (EXCEEDS 0.02 tolerance)

- Split 2025-H2 CP23: Ridge MAE=0.6685, GFS-res MAE=0.5924
  - ECMWF-res MAE=0.5761: improvement of -0.0163 (OK)
  - Ensemble MAE=0.5435: improvement of -0.0489 (OK)

ECMWF-residual alone passes Gate 2 in BOTH splits. Since the prereg prefers
ECMWF-res over ensemble, and ECMWF-res passes all 5 gates, the correct
verdict per the prereg is GO with best_candidate=ecmwf_residual.

The KILL is therefore INCORRECT. The implementation faithfully computed the
numbers but applied the gate logic too broadly.

### 7. Determinism: seed 42, lightgbm deterministic
**PASS**

Evidence:
- `scripts/evaluate_ecmwf_ensemble_point_gain.py:22`: `SEED = 42`
- `core/models/residual_lgbm.py:119-125`:
  ```
  "seed": config.seed,
  "deterministic": True,
  "force_col_wise": True,
  "num_threads": 1,
  ```
- Risk model: `fit_risk_model(lw_tr, seed=SEED)` uses LogisticRegression
  with `random_state=seed` (line 155 of late_warming_risk.py)
- `np.random.seed(SEED)` at script top

Fully reproducible.

### 8. Forbidden files
**PASS**

`git status --short` shows only:
- M references/code-reviews/update.txt (unrelated)
- ?? contracts/ecmwf_ensemble_point_gain_v0_prereg.md (the prereg itself)
- ?? reports/nwp/ecmwf_ensemble_point_gain.{json,md} (allowed outputs)
- ?? scripts/evaluate_ecmwf_ensemble_point_gain.py (allowed)

No changes to: decide.py, decision/**, Polymarket, calibration, contracts
(other than prereg), gate thresholds. `git diff --stat` confirms only
references/code-reviews/update.txt modified (not forbidden).

### 9. Is the gain real (not bracket-edge / degenerate split)?
**N/A (verdict should be GO, not KILL)**

ECMWF-residual gains are substantial and consistent:
- Split 2025-H1 CP20-22: dMAE -0.10 to -0.28 vs best existing (ALL stratum)
- Split 2025-H2 CP20-22: dMAE -0.05 to -0.09 vs GFS-res
- n=178/184 per split - not degenerate
- Gains appear across ALL strata and the pocket

The gains are NOT bracket-edge: ECMWF-res MAE improvements of 0.10-0.28 degC
are well beyond the 1-degC bracket resolution.

### 10. Overfitting the short window or per-split tuning?
**PASS (no overfitting signal)**

- No hyperparameter search (grep confirms no GridSearch/optuna/etc.)
- Same ResidualLgbmConfig used for all splits and all candidates
- N_ESTIMATORS=200 with early_stopping (not tuned per split)
- ECMWF-res gains are consistent across BOTH splits at CP20-22
- The ensemble actually performs WORSE than ECMWF-res alone in split 2025-H1,
  which is the opposite of an overfitting pattern (more parameters = worse)

---

## Summary of Findings

| Check | Result | Notes |
|-------|--------|-------|
| 1. Same test rows | PASS | Intersection enforced |
| 2. Causal NWP | PASS | 60min safety margin, both models |
| 3. Train-only thresholds | PASS | climo, c30, delta_p50 all train-only |
| 4. Ex-ante regime, canonical P30 | PASS | No P70 drift |
| 5. Honest walk-forward labelling | PASS | Shorter window noted |
| 6. Gate logic matches prereg | FAIL | Gate 2 too strict; ECMWF-res passes |
| 7. Determinism | PASS | seed 42, deterministic=True, num_threads=1 |
| 8. Forbidden files | PASS | None touched |
| 9. Gain reality | PASS | Substantial, consistent, not bracket-edge |
| 10. No overfitting | PASS | Fixed hyperparams, consistent across splits |

---

## Critical Finding: Incorrect KILL Verdict

The KILL is produced by a gate logic bug, not by the data. ECMWF-residual
(the prereg's preferred candidate) passes ALL 5 gates:

1. Beats best existing at CP20-22 in both splits: PASS
2. CP23 regression: +0.006 and -0.016 (both within 0.02): PASS
3. Pocket gain: dMAE -0.10 to -0.16 at CP20-22 in H1: PASS
4. Causal/deterministic: PASS
5. No exec/calib change: PASS

Per the prereg: "GO = the simplest candidate (prefer ECMWF-residual, then
ensemble) meeting 1-4." ECMWF-residual meets all criteria.

The correct verdict should be: **GO, best_candidate=ecmwf_residual**

The ensemble should NOT be promoted (it regresses CP23), but that does not
invalidate ECMWF-residual which the prereg explicitly prefers.

---

## Recommendation

The implementation is leak-free and methodologically excellent. The only
defect is the gate 2 evaluation logic which should check candidates
independently (preferred first) rather than globally. The script should be
re-run with corrected gate logic, or the report manually amended to reflect
that ECMWF-residual alone passes all gates.

This review does NOT modify the implementation per the review-only mandate.
