# CQR Over-Coverage Diagnostic (D1-D6) -- Phase 4 post-KILL

**Dominant failure mode: F3** (descriptive evidence, NOT a gate or a remedy choice)

- git_sha: `c897ecf83daeb93d3f00bd7c00d803a594f13496`  seed: 42  n_estimators: 500
- Companion to the frozen KILL: `reports/calibration/cqr_lightgbm_quantile_v0.{md,json}`.
- D6 is an ORACLE lower-bound (peeks at test truth); `oracle_lower_bound_diagnostic_only: true`. Never a model-selection signal.

## Verdict evidence

| metric | value |
|--------|-------|
| mean_crossing_freq | 0.0002 |
| mean_base_band_coverage | 0.8752 |
| mean_cqr_width_fraction | 0.1214 |
| mean_coverage_width_slope | 0.0496 |
| mean_oracle_floor_width_ALL | 10.0 |

**Contributions:**
- `F3` -- base band already over-covers (0.875) and CQR adds little width (frac=0.121)
- `F1` -- coverage rises with width (slope 0.050)
- `F3` -- oracle 80% floor width 10.00 brackets (integer granularity)

_Descriptive evidence, not a decision. F3 (integer-granularity floor / CQR-can-only-widen) dominates when present because no conformal remedy can narrow below the oracle floor. See research/RESEARCH_CQR_OVERCOVERAGE_AND_ALTERNATIVES.md section 6 for the branch._

## Per-split diagnostics

### full-2023 (n=1460)

- D1 pinball: q10=0.1999  q90=0.2465
- D2 coverage: base-band=0.8815  post-CQR=0.9219
- D3 coverage~width slope: 0.0653
- D4 raw crossing freq: 0.0
- D5 width: base=3.724  cqr=4.2295  cqr_frac=0.1195  E={'min': -2.3508, 'median': -0.434, 'max': 2.6965, 'frac_positive': 0.2888, 'n': 516}
- D6 oracle floor (integer brackets) vs CQR width:

  | stratum | n | oracle_min_width_80 | cqr_mean_width |
  |---------|---|---------------------|----------------|
  | ALL | 1460 | 10 | 4.2295 |
  | calm | 412 | 8 | 4.5121 |
  | non_calm | 1048 | 9 | 4.1183 |
  | high_delta | 952 | 9 | 4.1975 |
  | late_cp_23 | 365 | 10 | 4.137 |

### full-2024 (n=1464)

- D1 pinball: q10=0.1811  q90=0.244
- D2 coverage: base-band=0.8531  post-CQR=0.9044
- D3 coverage~width slope: 0.0202
- D4 raw crossing freq: 0.0007
- D5 width: base=3.1837  cqr=3.7876  cqr_frac=0.1594  E={'min': -2.0924, 'median': -0.3145, 'max': 2.9973, 'frac_positive': 0.323, 'n': 808}
- D6 oracle floor (integer brackets) vs CQR width:

  | stratum | n | oracle_min_width_80 | cqr_mean_width |
  |---------|---|---------------------|----------------|
  | ALL | 1464 | 10 | 3.7876 |
  | calm | 424 | 8 | 4.0 |
  | non_calm | 1040 | 10 | 3.701 |
  | high_delta | 948 | 10 | 3.7152 |
  | late_cp_23 | 366 | 10 | 3.1448 |

### full-2025 (n=1460)

- D1 pinball: q10=0.1638  q90=0.2247
- D2 coverage: base-band=0.8911  post-CQR=0.9274
- D3 coverage~width slope: 0.0632
- D4 raw crossing freq: 0.0
- D5 width: base=3.4932  cqr=3.8185  cqr_frac=0.0852  E={'min': -2.7771, 'median': -0.384, 'max': 2.8953, 'frac_positive': 0.28, 'n': 1100}
- D6 oracle floor (integer brackets) vs CQR width:

  | stratum | n | oracle_min_width_80 | cqr_mean_width |
  |---------|---|---------------------|----------------|
  | ALL | 1460 | 10 | 3.8185 |
  | calm | 488 | 8 | 4.1311 |
  | non_calm | 972 | 9 | 3.6615 |
  | high_delta | 944 | 10 | 3.732 |
  | late_cp_23 | 365 | 10 | 3.2247 |

## Notes

- Read-only diagnostic. No gate re-opened, no remedy run (reviewer directive).
- CQR config re-fit identically to the frozen eval (same fit/calib/test slices, seed 42, n_estimators=500).
- F1/F2/F3 mapping per research/RESEARCH_CQR_OVERCOVERAGE_AND_ALTERNATIVES.md section 6.

