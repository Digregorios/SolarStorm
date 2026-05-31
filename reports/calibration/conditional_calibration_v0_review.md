# conditional_calibration_v0 (T-9-3) - Anti-Leakage / Calibration Review

Reviewer: Kiro (automated)
Date: 2026-05-31
Prereg: contracts/conditional_calibration_v0_prereg.md
Implementation: scripts/evaluate_conditional_calibration.py
Outputs: reports/calibration/conditional_calibration_v0.{md,json}

---

## Checklist

### 1. REGIME ex-ante / causal (NOT truth-derived)

**PASS**

Evidence:
- scripts/evaluate_conditional_calibration.py:163-167: risk model fit on
  `rp_train = rp.filter(rp["date_local"] < cal_start)` (train dates only).
- scripts/evaluate_conditional_calibration.py:169: `c30 = float(np.percentile(train_risk, 30))`
  computed from TRAIN predicted risk only.
- scripts/evaluate_conditional_calibration.py:196-197: regime assigned via
  `predict_risk(risk_mdl, rp_sub)` which uses only the 5 pre-CP features
  (delta_06_to_cp, southerly_at_cp, rain_persistence_path, month_sin, month_cos).
- core/models/late_warming_risk.py:168-175: `predict_risk` uses `_matrix(df, model.feats)`
  which extracts only feature columns, never the `target` column.
- core/models/late_warming_risk.py:73: `build_features` filters obs to
  `ts_utc < cp_utc` (strict pre-CP causality).
- The regime label is a PREDICTED probability threshold, not derived from the
  realized Tmax or any post-CP observation.

### 2. Conformal offsets + c30 fit on CALIB/TRAIN only; calib disjoint from test

**PASS**

Evidence:
- scripts/evaluate_conditional_calibration.py:121-130:
  - `cal_start = s.train_end - timedelta(days=CALIB_DAYS - 1)`
  - `calib_panel`: `date_local in [cal_start, train_end]`
  - `test_panel`: `date_local in [test_start, test_end]`
- core/eval/cv.py:33: `tr_end = ts - timedelta(days=1)` so
  `train_end = test_start - 1 day`. Calib ends at train_end; test starts at
  test_start. Strictly disjoint (1-day gap minimum).
- Conformal offsets (both baseline and conditional) are fit on `resid_calib`
  (line 231) and `y_calib` (line 214). Never on test data.
- Ridge model fit on `train_panel` (line 137), which excludes calib.

### 3. Het gate reused UNCHANGED ([0.70, 0.90] band, per split, never pooled)

**PASS**

Evidence:
- scripts/evaluate_conditional_calibration.py:67-68: calls
  `heteroscedasticity_gate(lo.tolist(), hi.tolist(), y.tolist())` with no
  overridden low/high parameters.
- core/eval/gates_phase5.py:74-75: defaults are `low=HETEROSCED_COVERAGE_LOW`,
  `high=HETEROSCED_COVERAGE_HIGH`.
- core/contracts/phase5.py:104-105: `HETEROSCED_COVERAGE_LOW = 0.70`,
  `HETEROSCED_COVERAGE_HIGH = 0.90`.
- The gate is called per-split inside the loop (line 222 for baseline, line 260
  for conditional). Never pooled across splits.

### 4. Global coverage in [0.78, 0.86] in >=2/3 splits

**FAIL (correctly reported as FAIL in the output)**

Numbers from JSON:
- 2023: conditional global_coverage = 0.9274 (ABOVE 0.86)
- 2024: conditional global_coverage = 0.9103 (ABOVE 0.86)
- 2025: conditional global_coverage = 0.9096 (ABOVE 0.86)

0/3 splits in band. Gate G1 = False. Report is honest.

### 5. Conditional method gate-2 (het OR per-regime [0.74, 0.86] both regimes >=2/3)

**FAIL (correctly reported as FAIL in the output)**

Het gate: FAIL all 3 splits (JSON: het_gate_pass = false for all).
Per-regime coverage:
- 2023: calm=0.9611, non_calm=0.9142 (both > 0.86)
- 2024: calm=0.9424, non_calm=0.8982 (both > 0.86)
- 2025: calm=0.9319, non_calm=0.8995 (both > 0.86)

0/3 splits pass the regime-conditional target. Gate G2 = False. Report is honest.

### 6. WIDTH-INFLATION CHECK

**PASS (no inflation gaming)**

Mean widths (conditional vs v1.0 baseline):
- 2023: 4.40 vs 4.27 (delta = +0.13)
- 2024: 4.56 vs 4.28 (delta = +0.28)
- 2025: 3.98 vs 3.77 (delta = +0.21)

All deltas < +0.5. The method does NOT pass coverage by inflating width (it
doesn't pass coverage at all -- the over-coverage is structural, not
inflation-driven). Gate G3 = True. Honest.

### 7. Verdict consistent with prereg honest prior

**PASS**

The prereg states: "the a-priori probability that ANY reshaping passes the gate
is LOW" and "the structural over-coverage is STRUCTURAL". The KILL verdict
confirms this prior. The diagnosis correctly identifies:
- BOTH regimes over-cover (calm mean 0.945, non_calm mean 0.904)
- All CPs over-cover uniformly (0.911-0.920)
- Root cause: integer quantization + finite-sample conformal rank
- Next candidate: NWP-spread sigma

This is an honest negative result with diagnostic value, exactly as the prereg
anticipated.

### 8. Same panel/rows for v1.0 baseline vs conditional method

**PASS**

Evidence:
- scripts/evaluate_conditional_calibration.py:213-222 (baseline) and 226-261
  (conditional) both operate on the same `test_panel`, `y_test`, `cp_test`.
- JSON confirms identical `regime_n` for both methods within each split
  (e.g., 2023: calm=411, non_calm=1049 for both).

### 9. Per-split tuning of c30/regimes/coverage target

**PASS (no tuning detected)**

- COVERAGE = 0.80 (module constant, line 49)
- MIN_CALIB = 30 (module constant, line 48)
- c30 = train P30 (line 169) -- this is the prereg-specified formula, not a
  tuned parameter. It varies per split only because the train set expands
  (expanding window), which is correct walk-forward behavior.
- Regime definitions ("calm"/"non_calm") are fixed strings.
- No conditional logic that changes parameters based on split identity.

### 10. Forbidden files touched

**PASS (none touched)**

`git status --short` output:
```
 M references/code-reviews/update.txt
?? artifacts/
?? contracts/conditional_calibration_v0_prereg.md
?? projetos_github/
?? quarentena/
?? reports/calibration/
?? scripts/evaluate_conditional_calibration.py
```

`git diff --stat`: only `references/code-reviews/update.txt` modified (154
insertions, 25 deletions -- review notes, not forbidden scope).

No modifications to:
- core/cli/decide.py
- core/decision/**
- Polymarket/execution code
- contracts/ (prereg is untracked/new, not a modification)
- reports/phase5_closure.md
- Gate thresholds (core/contracts/phase5.py unchanged)

---

## Summary Table

| # | Check | Verdict |
|---|-------|---------|
| 1 | Regime ex-ante/causal | PASS |
| 2 | Calib/train only, disjoint from test | PASS |
| 3 | Het gate unchanged [0.70,0.90] | PASS |
| 4 | Global cov in [0.78,0.86] >=2/3 | FAIL (correctly reported) |
| 5 | Gate-2 conditional target | FAIL (correctly reported) |
| 6 | Width inflation | PASS (no gaming) |
| 7 | Verdict consistent with prereg prior | PASS |
| 8 | Same rows for comparison | PASS |
| 9 | No per-split tuning | PASS |
| 10 | No forbidden files touched | PASS |

---

## Overall Verdict

**PASS -- the implementation faithfully and leak-free realizes the prereg, and
the KILL conclusion is honest and well-supported.**

The KILL is a legitimate negative result:
- No truth leakage (regime is ex-ante from predicted risk, c30 from train).
- No data leakage (calib strictly disjoint from test, model fit on train only).
- No gate relaxation (het gate band unchanged at [0.70,0.90]).
- No width inflation gaming (deltas +0.13 to +0.28, well under +0.5).
- The structural over-coverage persists in BOTH regimes and ALL CPs, confirming
  the Phase 5 closure diagnosis that it is irreducible with local features.
- The diagnostic value is delivered: calm regime is worst (mean 0.945) but
  non_calm also over-covers (0.904), so no ex-ante partition fixes this.

A well-supported KILL with honest diagnosis is the expected outcome per the
prereg's stated prior. No flags raised.
