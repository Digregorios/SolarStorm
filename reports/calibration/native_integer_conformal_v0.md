# T-9-5 native_integer_conformal_v0: KILL

**Verdict:** KILL
**Promoted:** None
**Diagnosis:** het gate FAIL: over-coverage persists even native-integer; the slack is integer granularity itself, not Q-after; global coverage outside [0.78, 0.86]; Recommend T-9-7 diagnostic stopgap.

## Per-split results

| Split | Method | Coverage | Width | Het Pass |
|-------|--------|----------|-------|----------|
| 2023-01-01 | v1.0 | 0.9205 | 4.27 | False |
| 2023-01-01 | M1 | 0.9582 | 5.00 | False |
| 2023-01-01 | M2 | 0.9144 | 4.25 | False |
| 2024-01-01 | v1.0 | 0.9055 | 4.28 | False |
| 2024-01-01 | M1 | 0.9089 | 4.50 | False |
| 2024-01-01 | M2 | 0.8568 | 4.00 | False |
| 2025-01-01 | v1.0 | 0.8925 | 3.77 | False |
| 2025-01-01 | M1 | 0.8836 | 4.00 | False |
| 2025-01-01 | M2 | 0.8760 | 3.75 | True |

## Gate summary

- M1: cov_in_band=0/3, het_pass=0/3, width_lower=0/3 -> FAIL
- M2: cov_in_band=1/3, het_pass=1/3, width_lower=3/3 -> FAIL
