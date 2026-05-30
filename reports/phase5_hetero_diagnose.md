# Phase 5 - Track A diagnose-first (heteroscedasticity; read-only)

- Method: `normalized_quantization_aware` (sigma_hat = sqrt(`p50_var`))
- Heteroscedasticity band: `0.70 .. 0.90` (4 width-quartile bins); per-CP window `90` d
- No model/gate/contract changed. Diagnostics only.

## sigma_hat distribution (frozen calib median/floor reused on test)

| split | role | p01 | p25 | p50 | p75 | p95 | p99 | max | tail p99/p50 |
|-------|------|-----|-----|-----|-----|-----|-----|-----|--------------|
| 2023-01-01_to_2023-12-31 | calib | 0.01 | 0.10 | 0.10 | 0.10 | 0.31 | 0.58 | 1.05 | 5.86 |
| 2023-01-01_to_2023-12-31 | test | 0.00 | 0.10 | 0.10 | 0.11 | 0.32 | 0.67 | 0.95 | 6.73 |
| 2024-01-01_to_2024-12-30 | calib | 0.01 | 0.11 | 0.11 | 0.11 | 0.36 | 0.66 | 1.22 | 6.23 |
| 2024-01-01_to_2024-12-30 | test | 0.00 | 0.11 | 0.11 | 0.12 | 0.32 | 0.61 | 0.97 | 5.81 |
| 2025-01-01_to_2025-12-31 | calib | 0.01 | 0.11 | 0.11 | 0.11 | 0.32 | 0.55 | 1.00 | 4.94 |
| 2025-01-01_to_2025-12-31 | test | 0.01 | 0.11 | 0.11 | 0.11 | 0.34 | 0.63 | 0.88 | 5.62 |

## Integer width frequency (test)

| split | width:frac (each emitted width) | distinct | mean |
|-------|----------------------------------|----------|------|
| 2023-01-01_to_2023-12-31 | 1:0.063 2:0.235 3:0.494 4:0.063 5:0.058 6:0.027 7:0.023 8:0.006 9:0.010 10:0.003 11:0.002 12:0.002 13:0.005 14:0.002 15:0.003 16:0.001 17:0.001 18:0.001 | 18 | 3.29 |
| 2024-01-01_to_2024-12-30 | 1:0.061 2:0.090 3:0.492 4:0.197 5:0.053 6:0.030 7:0.023 8:0.016 9:0.013 10:0.005 11:0.003 12:0.001 13:0.003 14:0.003 15:0.001 16:0.001 17:0.001 18:0.001 19:0.001 20:0.001 21:0.002 | 21 | 3.71 |
| 2025-01-01_to_2025-12-31 | 1:0.101 2:0.474 3:0.292 4:0.069 5:0.024 6:0.017 7:0.005 8:0.005 9:0.004 10:0.002 11:0.005 12:0.001 | 12 | 2.63 |

## Width vs |error_int| correlation (test)

| split | pearson | spearman |
|-------|---------|----------|
| 2023-01-01_to_2023-12-31 | 0.055 | 0.014 |
| 2024-01-01_to_2024-12-30 | 0.114 | 0.103 |
| 2025-01-01_to_2025-12-31 | 0.067 | 0.075 |

## Per width-quartile mechanism (test; gate-mirrored bins)

_slack = mean_width - (2*mean|error_int| + 1). Positive slack in wide bins = sigma over-states difficulty (interval wider than the realized miss needs)._

| split | bin [w_lo-w_hi] | n | coverage | mean width | mean|e| | needed | slack | in band |
|-------|-----------------|---|----------|------------|---------|--------|-------|---------|
| 2023-01-01_to_2023-12-31 | [1-5] | 1333 | 0.821 | 2.80 | 0.76 | 2.52 | 0.29 | True |
| 2023-01-01_to_2023-12-31 | [6-9] | 98 | 1.000 | 6.99 | 0.68 | 2.37 | 4.62 | False |
| 2023-01-01_to_2023-12-31 | [10-13] | 18 | 1.000 | 11.83 | 1.39 | 3.78 | 8.06 | False |
| 2023-01-01_to_2023-12-31 | [14-18] | 11 | 1.000 | 15.45 | 1.00 | 3.00 | 12.45 | False |
| 2024-01-01_to_2024-12-30 | [1-5] | 1304 | 0.868 | 3.10 | 0.70 | 2.40 | 0.70 | True |
| 2024-01-01_to_2024-12-30 | [6-10] | 127 | 0.992 | 7.32 | 0.80 | 2.61 | 4.72 | False |
| 2024-01-01_to_2024-12-30 | [11-15] | 18 | 1.000 | 12.78 | 0.89 | 2.78 | 10.00 | False |
| 2024-01-01_to_2024-12-30 | [16-21] | 11 | 1.000 | 18.73 | 1.64 | 4.27 | 14.45 | False |
| 2025-01-01_to_2025-12-31 | [1-3] | 1266 | 0.783 | 2.22 | 0.65 | 2.30 | -0.08 | True |
| 2025-01-01_to_2025-12-31 | [4-6] | 161 | 0.988 | 4.53 | 0.65 | 2.30 | 2.22 | False |
| 2025-01-01_to_2025-12-31 | [7-9] | 22 | 1.000 | 7.91 | 0.59 | 2.18 | 5.73 | False |
| 2025-01-01_to_2025-12-31 | [10-12] | 11 | 1.000 | 10.82 | 1.64 | 4.27 | 6.55 | False |

## Reading

- If the widest quartile carries large positive **slack** with coverage ~1.00,
  the sigma_hat tail inflates widths beyond the realized error -> a sigma-tail
  taming hypothesis (winsorize / transform / Mondrian by sigma-bucket) is indicated.
- If width vs |error| correlation is weak, width is not tracking difficulty at all
  -> the proxy itself is suspect (separate, pre-registered question; not this change).
