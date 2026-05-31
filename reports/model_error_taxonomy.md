# Model Error Taxonomy (T-10-3)

Ridge point forecast at CP 23:00, walk-forward ['2023-01-01', '2024-01-01', '2025-01-01'].

- N = 1096, overall MAE = 0.7 degC, bias = 0.025, bracket-miss = 0.5593

## Strata breakdown

| Stratum | n | MAE | Bias | Bracket-miss | Error share |
|---------|---|-----|------|--------------|-------------|
| DIAG_material_late_warming [POST-HOC] | 409 | 0.868 | -0.79 | 0.6235 | 46.3% |
| DIAG_no_late_warming [POST-HOC] | 687 | 0.6 | 0.509 | 0.5211 | 53.7% |
| DIAG_tmax_already_reached [POST-HOC] | 279 | 0.892 | 0.828 | 0.7419 | 32.5% |
| DIAG_tmax_not_yet_reached [POST-HOC] | 817 | 0.634 | -0.25 | 0.4969 | 67.5% |
| delta06_bin_high | 509 | 0.709 | -0.045 | 0.5481 | 47.1% |
| delta06_bin_low | 173 | 0.642 | 0.098 | 0.5434 | 14.5% |
| delta06_bin_mid | 414 | 0.713 | 0.08 | 0.5797 | 38.5% |
| month_01 | 93 | 0.989 | -0.366 | 0.6667 | 12.0% |
| month_02 | 85 | 0.741 | -0.012 | 0.5412 | 8.2% |
| month_03 | 93 | 0.71 | -0.022 | 0.5484 | 8.6% |
| month_04 | 90 | 0.6 | 0.244 | 0.5333 | 7.0% |
| month_05 | 93 | 0.72 | 0.333 | 0.6022 | 8.7% |
| month_06 | 90 | 0.689 | 0.0 | 0.5222 | 8.1% |
| month_07 | 93 | 0.559 | -0.065 | 0.4516 | 6.8% |
| month_08 | 93 | 0.602 | 0.0 | 0.5269 | 7.3% |
| month_09 | 90 | 0.656 | -0.189 | 0.5556 | 7.7% |
| month_10 | 93 | 0.71 | 0.022 | 0.6022 | 8.6% |
| month_11 | 90 | 0.711 | 0.111 | 0.5778 | 8.3% |
| month_12 | 93 | 0.71 | 0.237 | 0.5806 | 8.6% |
| rain_persist_no | 966 | 0.708 | 0.004 | 0.56 | 89.2% |
| rain_persist_yes | 130 | 0.638 | 0.177 | 0.5538 | 10.8% |
| regime_exante_calm | 331 | 0.625 | 0.082 | 0.5347 | 27.0% |
| regime_exante_non_calm | 765 | 0.732 | 0.0 | 0.5699 | 73.0% |
| s_to_n_no | 1037 | 0.686 | 0.018 | 0.5526 | 92.7% |
| s_to_n_yes | 59 | 0.949 | 0.136 | 0.678 | 7.3% |
| season_DJF | 271 | 0.815 | -0.048 | 0.5978 | 28.8% |
| season_JJA | 276 | 0.616 | -0.022 | 0.5 | 22.2% |
| season_MAM | 276 | 0.678 | 0.185 | 0.5616 | 24.4% |
| season_SON | 273 | 0.692 | -0.018 | 0.5788 | 24.6% |
| wind_northerly | 739 | 0.698 | 0.0 | 0.5589 | 67.3% |
| wind_southerly | 357 | 0.703 | 0.076 | 0.5602 | 32.7% |

## TOP-5 ranked error pockets

| Rank | Stratum | Share | MAE | n | Actionable |
|------|---------|-------|-----|---|------------|
| 1 | regime_exante_non_calm | 73.0% | 0.732 | 765 | EX-ANTE actionable |
| 2 | delta06_bin_high | 47.1% | 0.709 | 509 | EX-ANTE actionable |
| 3 | DIAG_material_late_warming | 46.3% | 0.868 | 409 | POST-HOC only |
| 4 | delta06_bin_mid | 38.5% | 0.713 | 414 | EX-ANTE actionable |
| 5 | wind_southerly | 32.7% | 0.703 | 357 | EX-ANTE actionable |

---
Seed 42. Anti-leakage: regime strata use EX-ANTE predicted risk (calm = bottom-30% predicted risk; non_calm = risk >= train P30, the calm_day_filter_v0 c30). DIAG_ strata are POST-HOC (truth-derived).
