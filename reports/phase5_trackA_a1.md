# Phase 5 - Track A.A1: sigma winsorization (one-shot)

- Hypothesis: `trackA_a1_sigma_winsor` (conformal_method_version `1.1`; pre-reg sha256 `ea5b279a70c9b889...`)
- Change: winsorize `sigma_hat = sqrt(p50_var)` to calib-frozen `[P25, P95]`, used in score u AND interval.
- Unchanged gates: coverage `0.80 +/- 0.04`; het per-width-quartile in `[0.70, 0.90]` (4 bins); run_id `20260530T012449Z`.

- **ACCEPT A1: True**  (wide-bin over-coverage reduced all splits: True; KILL hit: False)
- **Heteroscedasticity passed (all splits): False**
- **Coverage within tol (all splits): False**
- Calib global in band (all splits): True
- Widths non-degenerate (all splits): True
- Test reuses calib clip (no leak, all splits): True

## Effective clip bounds per split (calib-frozen; reused on test)

| split | clip_lo | clip_hi | test reuses clip | calib cov (after) | in band |
|-------|---------|---------|------------------|-------------------|---------|
| 2023-01-01_to_2023-12-31 | 0.099 | 0.309 | True | 0.8034 | True |
| 2024-01-01_to_2024-12-30 | 0.105 | 0.360 | True | 0.7972 | True |
| 2025-01-01_to_2025-12-31 | 0.111 | 0.317 | True | 0.8000 | True |

## Per-width-quartile coverage: BEFORE (v1.0) vs AFTER (winsorized)

| split | arm | per-bin coverage [w_lo-w_hi] cov (n) | het passed |
|-------|-----|--------------------------------------|------------|
| 2023-01-01_to_2023-12-31 | before | [1-5] 0.821 (n=1333); [6-9] 1.000 (n=98); [10-13] 1.000 (n=18); [14-18] 1.000 (n=11) | False |
| 2023-01-01_to_2023-12-31 | after | [2-2] 0.740 (n=569); [3-3] 0.896 (n=646); [4-4] 0.926 (n=94); [5-6] 0.947 (n=151) | False |
| 2024-01-01_to_2024-12-30 | before | [1-5] 0.868 (n=1304); [6-10] 0.992 (n=127); [11-15] 1.000 (n=18); [16-21] 1.000 (n=11) | False |
| 2024-01-01_to_2024-12-30 | after | [2-3] 0.866 (n=1198); [4-4] 0.930 (n=100); [5-5] 0.966 (n=58); [6-7] 0.981 (n=104) | False |
| 2025-01-01_to_2025-12-31 | before | [1-3] 0.783 (n=1266); [4-6] 0.988 (n=161); [7-9] 1.000 (n=22); [10-12] 1.000 (n=11) | False |
| 2025-01-01_to_2025-12-31 | after | [2-2] 0.766 (n=1018); [3-3] 0.913 (n=300); [4-4] 0.959 (n=123); [5-5] 1.000 (n=19) | False |

## Width non-degeneracy + global coverage (after)

| split | distinct widths | width std | mean width | test coverage | within tol |
|-------|-----------------|-----------|------------|---------------|------------|
| 2023-01-01_to_2023-12-31 | 5 | 1.04 | 2.92 | 0.8425 | False |
| 2024-01-01_to_2024-12-30 | 6 | 1.14 | 3.18 | 0.8822 | False |
| 2025-01-01_to_2025-12-31 | 4 | 0.70 | 2.41 | 0.8158 | True |

## Notes

- ECE is a separate track (C); NOT bundled here (one hypothesis per change-set).
- het gate is the unchanged binding bar, evaluated per split (never pooled).
- no percentile/window/proxy/c-rule re-tuning after results (anti-gaming).
