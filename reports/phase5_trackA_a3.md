# Phase 5 - Track A.A3: Mondrian conditional conformal by sigma bucket (one-shot)

- Hypothesis: `trackA_a3_mondrian_sigma_bucket` (conformal_method_version `1.2`; pre-reg sha256 `ee0ac6f232490b74...`)
- Change: per-`sigma_hat`-bucket shrunk tail quantiles (`n_buckets=4`, edges via `np.quantile(0.25, 0.5, 0.75)` method=`linear`, frozen-on-calib; `min_n_bucket=50`; shrinkage `n0=200.0`); `c` global per split.
- Unchanged gates: coverage `0.80 +/- 0.04`; het per-width-quartile in `[0.70, 0.90]` (4 bins); run_id `20260530T024825Z`.

- **ACCEPT A3: False**  (het gate passes all splits: False; KILL hit: False)
- **Heteroscedasticity passed (all splits): False**
- **Coverage within tol (all splits): False**
- Calib global in band (all splits): True
- Widths non-degenerate (all splits): True
- Buckets non-empty after merge (all splits): True
- Test reuses calib partition (no leak, all splits): True

## Frozen sigma-bucket partition per split (calib; reused on test)

| split | eff buckets | calib counts | merged edges | calib cov (after) | in band |
|-------|-------------|--------------|--------------|-------------------|---------|
| 2023-01-01_to_2023-12-31 | 3 | [89, 178, 89] | 0.099, 0.099 | 0.8034 | True |
| 2024-01-01_to_2024-12-30 | 3 | [90, 180, 90] | 0.105, 0.105 | 0.7972 | True |
| 2025-01-01_to_2025-12-31 | 3 | [90, 180, 90] | 0.111, 0.112 | 0.8000 | True |

## Per-bucket shrunk quantiles (after)

| split | bucket | n | q_lo_eff | q_hi_eff |
|-------|--------|---|----------|----------|
| 2023-01-01_to_2023-12-31 | 0 | 89 | -12.922 | 10.088 |
| 2023-01-01_to_2023-12-31 | 1 | 178 | -9.014 | 7.728 |
| 2023-01-01_to_2023-12-31 | 2 | 89 | -7.132 | 6.624 |
| 2024-01-01_to_2024-12-30 | 0 | 90 | -11.380 | 14.366 |
| 2024-01-01_to_2024-12-30 | 1 | 180 | -7.974 | 11.562 |
| 2024-01-01_to_2024-12-30 | 2 | 90 | -6.203 | 9.633 |
| 2025-01-01_to_2025-12-31 | 0 | 90 | -8.190 | 5.465 |
| 2025-01-01_to_2025-12-31 | 1 | 180 | -4.867 | 5.331 |
| 2025-01-01_to_2025-12-31 | 2 | 90 | -4.013 | 4.124 |

## Per-width-quartile coverage: BEFORE (v1.0) vs AFTER (Mondrian)

| split | arm | per-bin coverage [w_lo-w_hi] cov (n) | het passed |
|-------|-----|--------------------------------------|------------|
| 2023-01-01_to_2023-12-31 | before | [1-5] 0.821 (n=1333); [6-9] 1.000 (n=98); [10-13] 1.000 (n=18); [14-18] 1.000 (n=11) | False |
| 2023-01-01_to_2023-12-31 | after | [1-4] 0.817 (n=1336); [5-7] 1.000 (n=96); [8-10] 1.000 (n=15); [11-14] 1.000 (n=13) | False |
| 2024-01-01_to_2024-12-30 | before | [1-5] 0.868 (n=1304); [6-10] 0.992 (n=127); [11-15] 1.000 (n=18); [16-21] 1.000 (n=11) | False |
| 2024-01-01_to_2024-12-30 | after | [1-4] 0.871 (n=1304); [5-7] 0.983 (n=118); [8-11] 1.000 (n=26); [12-16] 1.000 (n=12) | False |
| 2025-01-01_to_2025-12-31 | before | [1-3] 0.783 (n=1266); [4-6] 0.988 (n=161); [7-9] 1.000 (n=22); [10-12] 1.000 (n=11) | False |
| 2025-01-01_to_2025-12-31 | after | [1-2] 0.731 (n=1121); [3-4] 0.917 (n=300); [5-6] 1.000 (n=27); [7-8] 0.917 (n=12) | False |

## Width non-degeneracy + global coverage (after)

| split | distinct widths | width std | mean width | test coverage | within tol |
|-------|-----------------|-----------|------------|---------------|------------|
| 2023-01-01_to_2023-12-31 | 14 | 1.46 | 2.98 | 0.8322 | True |
| 2024-01-01_to_2024-12-30 | 15 | 1.64 | 3.37 | 0.8836 | False |
| 2025-01-01_to_2025-12-31 | 8 | 0.90 | 2.26 | 0.7760 | True |

## Notes

- ECE is a separate track (C); NOT bundled here (one hypothesis per change-set).
- het gate is the unchanged binding bar, evaluated per split (never pooled).
- no n_buckets/n0/min_n/edge/quantile-method/c-rule re-tuning after results.
- A3 is a branch off v1.0 (NOT bundled with A1 winsorization).
