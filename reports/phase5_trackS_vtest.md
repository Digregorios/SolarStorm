# Phase 5 - Track S tail-budget vtest (CALIB-ONLY winner selection)

_Read-only calib analysis (test split untouched). Winner = min mean(slack) in the mod-wide REQ-AUD-5 bin at 22Z/23Z; tie -> S1. No contract/wiring/one-shot here._

- S1: alpha_lo=0.1, alpha_hi=0.1; S2: alpha_lo=0.05, alpha_hi=0.15 (both sum 0.20)
- Late-CP regime: 22:00, 23:00; per-CP window 90 d

- **WINNER: `S1`** (mean slack S1=`0.9651` vs S2=`1.5768`); winner global-sane: **False**

## Mod-wide bin slack at 22Z/23Z (calib-only, per split)

| split | arm | slack | mean_width | needed | cov_bin | in[0.70,0.90] | n | global calib cov | distinct w |
|-------|-----|-------|------------|--------|---------|---------------|---|------------------|------------|
| 2023-01-01_to_2023-12-31 | S1 | 1.124 | 3.45 | 2.33 | 0.876 | True | 113 | 0.9185 | 22 |
| 2023-01-01_to_2023-12-31 | S2 | 1.963 | 4.34 | 2.38 | 0.853 | True | 109 | 0.9101 | 23 |
| 2024-01-01_to_2024-12-30 | S1 | 0.880 | 3.47 | 2.59 | 0.852 | True | 108 | 0.9083 | 23 |
| 2024-01-01_to_2024-12-30 | S2 | 1.302 | 3.91 | 2.60 | 0.871 | True | 116 | 0.9000 | 25 |
| 2025-01-01_to_2025-12-31 | S1 | 0.892 | 3.14 | 2.25 | 0.842 | True | 120 | 0.8917 | 17 |
| 2025-01-01_to_2025-12-31 | S2 | 1.465 | 3.79 | 2.33 | 0.891 | True | 101 | 0.9056 | 19 |

## Notes

- CALIB-ONLY: test split never read; no contract/wiring/one-shot here.
- Winner = min mean(slack_modwide) over splits at 22Z/23Z; tie -> S1.
- alpha_lo + alpha_hi = 0.20 for both arms (nominal 0.80 budget; c-rule unchanged).
- Q, sigma proxy (sqrt p50_var), windows, splits all inherited from v1.0.
