# T-11-8: CQR LightGBM Quantile IC80 -- Phase 4 Evaluation

**Verdict: KILL**  (prereg contracts/cqr_lightgbm_quantile_v0_prereg.md v1.0, frozen gate)

- git_sha: `a83c44f63e44a1badac1cf86d2ae2ae57d218091`  seed: 42  deterministic: True  num_threads: 1
- n_estimators: 500  calib_frac: 0.2  coverage_target: 0.8
- Primary feature set: obs+GFS (best set spanning the 3-fold walk-forward; ECMWF/spread are ablations only)
- Gate aggregation: >= 2/3 splits satisfy each of conditions 1-5; condition 6 structural

## Gate (frozen conditions 1-6)

| # | Condition | per-split | pass |
|---|-----------|-----------|------|
| 1. global IC80 in [0.78,0.86] | [False, False, False] | FAIL |
| 2. REQ-AUD-5 het gate | [False, False, False] | FAIL |
| 3. width <= ridge_conformal_minimal | [True, True, False] | PASS |
| 4. RPS <= +2% vs ridge center (v1.0 proxy) | [True, False, True] | PASS |
| 5. hard-strata IC80 in band | [False, False, False] | FAIL |
| 6. disjoint/deterministic/no-tuning | structural | PASS |

**Failed:** c1_global_coverage_in_band, c2_het_gate, c5_no_hard_strata_regression

## L1/L2/width diagnostic per split (primary obs+GFS)

| split | n | global cov (L1) | het pass (L2) | CQR width | ridge width | CQR RPS | ridge RPS | RPS rel |
|-------|---|-----------------|---------------|-----------|-------------|---------|-----------|---------|
| full-2023 | 1460 | 0.9219 | False | 4.2295 | 4.5 | 0.6686 | 0.669 | -0.0007 |
| full-2024 | 1464 | 0.9044 | False | 3.7876 | 4.0 | 0.6619 | 0.6337 | 0.0445 |
| full-2025 | 1460 | 0.9274 | False | 3.8185 | 3.5 | 0.6069 | 0.6694 | -0.0934 |

## Per-stratum CQR IC80 coverage (primary)

| split | stratum | n | coverage | mean width |
|-------|---------|---|----------|------------|
| full-2023 | ALL | 1460 | 0.9219 | 4.2295 |
| full-2023 | calm | 412 | 0.9175 | 4.5121 |
| full-2023 | non_calm | 1048 | 0.9237 | 4.1183 |
| full-2023 | high_delta_06 | 952 | 0.9254 | 4.1975 |
| full-2023 | late_cp_23 | 365 | 0.9315 | 4.137 |
| full-2024 | ALL | 1464 | 0.9044 | 3.7876 |
| full-2024 | calm | 424 | 0.9175 | 4.0 |
| full-2024 | non_calm | 1040 | 0.899 | 3.701 |
| full-2024 | high_delta_06 | 948 | 0.8924 | 3.7152 |
| full-2024 | late_cp_23 | 366 | 0.9098 | 3.1448 |
| full-2025 | ALL | 1460 | 0.9274 | 3.8185 |
| full-2025 | calm | 488 | 0.9283 | 4.1311 |
| full-2025 | non_calm | 972 | 0.927 | 3.6615 |
| full-2025 | high_delta_06 | 944 | 0.9322 | 3.732 |
| full-2025 | late_cp_23 | 365 | 0.9452 | 3.2247 |

## Ablations (ECMWF overlap window, 2 folds)

_Single station (NZWN); spread ablation interacted with REGIME only (no cross-station interaction possible). The spread ablation (with vs without) is SAME-ROWS (both on the GFS+ECMWF ensemble panel). The ECMWF-add arms (obs_gfs vs obs_gfs_ecmwf) are rough context only: the GFS panel and ensemble panel can differ in date coverage, so it is NOT a strict same-rows comparison._

### ECMWF add (does ECMWF help over obs+GFS?)

| arm | global cov | mean width | het pass | n |
|-----|-----------|------------|----------|---|
| obs_gfs | 0.8952 | 4.8007 | False | 1460 |
| obs_gfs_ecmwf | 0.8829 | 4.5685 | False | 1460 |

### |GFS-ECMWF| spread ablation (with vs without the spread feature)

| arm | global cov | mean width | het pass | n |
|-----|-----------|------------|----------|---|
| with_spread | 0.8829 | 4.5685 | False | 1460 |
| without_spread | 0.8877 | 4.4274 | False | 1460 |

#### spread ablation x regime (coverage / mean width)

| arm | regime | n | coverage | mean width |
|-----|--------|---|----------|------------|
| with_spread | ALL | 1460 | 0.8829 | 4.5685 |
| with_spread | calm | 532 | 0.906 | 4.9718 |
| with_spread | non_calm | 928 | 0.8696 | 4.3373 |
| with_spread | high_delta_06 | 944 | 0.8612 | 4.4958 |
| without_spread | ALL | 1460 | 0.8877 | 4.4274 |
| without_spread | calm | 532 | 0.9079 | 4.7613 |
| without_spread | non_calm | 928 | 0.8761 | 4.236 |
| without_spread | high_delta_06 | 944 | 0.8655 | 4.3676 |

## Notes

- CALIBRATION-ONLY evaluation (IC80 interval). No execution, no Polymarket, no decision wiring.
- ridge_conformal_minimal computed on the SAME GFS-present rows as CQR (identical-rows width comparison).
- RPS baseline is the Ridge-band CENTER prob_dist (v1.0 center proxy); the full Phase-5 signed-conformal
  object is out of scope and would not change the CENTER's RPS.
- Conditions 1-5 require >= 2/3 splits; condition 6 is structural (disjoint/deterministic/frozen levels).

