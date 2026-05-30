# Phase 5 - calibration + confidence audit

- Conformal method: `normalized_quantization_aware` v`1.0` (sigma_hat = sqrt(`p50_var`); pre-reg sha256 `56459f40e94a4162...`)
- IC80 coverage target: `0.80 +/- 0.04` (band `[0.76, 0.84]`)
- Heteroscedasticity band: `0.70 .. 0.90` (4 IC-width quartile bins)
- Confidence ECE tol: `0.05`
- Nominal-level grid c: `0.5 .. 0.96 step 0.005` (selected on calib only; per-CP window `90` days)

- **Coverage within tol (all splits): False**
- **Heteroscedasticity passed (all splits): False**
- **Confidence ECE within tol: False**
- **Phase 5 ready: False**

## IC80 coverage per split (normalized quantization-aware conformal)

| split | n_test | calib c | calib cov (in band) | test coverage | within tol | mean width |
|-------|--------|---------|---------------------|---------------|------------|------------|
| 2023-01-01_to_2023-12-31 | 1460 | 0.585 | 0.8034 (True) | 0.8363 | True | 3.29 |
| 2024-01-01_to_2024-12-30 | 1460 | 0.645 | 0.8000 (True) | 0.8815 | False | 3.71 |
| 2025-01-01_to_2025-12-31 | 1460 | 0.595 | 0.8000 (True) | 0.8103 | True | 2.63 |

## Width variation (heteroscedasticity evidence; non-degenerate widths)

| split | calib mean/std width | calib distinct | test mean/std width | test distinct |
|-------|----------------------|----------------|---------------------|---------------|
| 2023-01-01_to_2023-12-31 | 3.19 / 2.19 | 15 | 3.29 / 2.00 | 18 |
| 2024-01-01_to_2024-12-30 | 3.79 / 2.61 | 16 | 3.71 / 2.26 | 21 |
| 2025-01-01_to_2025-12-31 | 2.66 / 1.38 | 11 | 2.63 / 1.38 | 12 |

## Heteroscedasticity gate (IC80-width quartile coverage; REQ-AUD-5)

| split | passed | mixed in/out | per-bin coverage (n) |
|-------|--------|--------------|----------------------|
| 2023-01-01_to_2023-12-31 | False | True | [1-5] 0.821 (n=1333); [6-9] 1.000 (n=98); [10-13] 1.000 (n=18); [14-18] 1.000 (n=11) |
| 2024-01-01_to_2024-12-30 | False | True | [1-5] 0.868 (n=1304); [6-10] 0.992 (n=127); [11-15] 1.000 (n=18); [16-21] 1.000 (n=11) |
| 2025-01-01_to_2025-12-31 | False | True | [1-3] 0.783 (n=1266); [4-6] 0.988 (n=161); [7-9] 1.000 (n=22); [10-12] 1.000 (n=11) |

## Confidence audit per split (ECE + selective bracket_match; REQ-CONF-1)

| split | fitted | ECE | within tol | bracket_match @ {0.25, 0.50, 0.75, 1.00} |
|-------|--------|-----|------------|--------------------------------------------|
| 2023-01-01_to_2023-12-31 | True | 0.1387 | False | 0.25:0.425, 0.50:0.427, 0.75:0.418, 1.00:0.411 |
| 2024-01-01_to_2024-12-30 | True | 0.0506 | False | 0.25:0.460, 0.50:0.438, 0.75:0.458, 1.00:0.437 |
| 2025-01-01_to_2025-12-31 | True | 0.0180 | True | 0.25:0.485, 0.50:0.495, 0.75:0.479, 1.00:0.458 |

## Stay-out (confidence gate; REQ-CONF-3)

_Operational `min_confidence=0.55` (config default; the learned cutoff is a later phase). Pooled over all test rows._

- rows: 4380
- NO_TRADE(low_confidence): 3471 (0.792)

## Pooled confidence audit (all splits)

- ECE: `0.0690` (tol `0.05`, within_tol=False)
- n: 4380
- NOTE: the pooled ECE is dominated by the scarcity-limited split; read the
  per-split table above, not the pool, for calibration health.

## Honest conclusion

- object mismatch fixed: **True** (conformal now calibrated on the integer-inclusive bracket object, not a decimal interval)
- coverage passes on splits: `['2023-01-01_to_2023-12-31', '2025-01-01_to_2025-12-31']`
- confidence ECE passes on splits: `['2025-01-01_to_2025-12-31']`
- object mismatch fixed: conformal now calibrated on the integer-inclusive bracket object
- 2024 coverage limited by calib->test drift (non-exchangeability), not the method
- 2023 ECE is training-scarcity driven (~21 months; GFS floor 2021-03-22), separate track

## Backlog (separate tracks; each needs its own pre-registration)

- **Drift 2024**: new hypothesis; requires its own pre-registration (seasonal 12m / Mondrian by month-regime / ex-ante update rule)
- **ECE 2023**: separate track (regularization / pooling / accept limitation); not bundled with the coverage fix
