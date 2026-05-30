# Clean backtest 2026-05-27..30 (live data, baseline empirical @ CP 23:00)

- n_scored: 4  bracket-match: 0.25  IC80 coverage: 1.0

| date | k_cp | p50 | IC80 | truth | bracket_match | in_IC80 | src |
|------|------|-----|------|-------|---------------|---------|-----|
| 2026-05-27 | 12 | 13 | [12, 17] | 15 | 0 | 1 | conditional |
| 2026-05-28 | 15 | 16 | [15, 18] | 17 | 0 | 1 | conditional |
| 2026-05-29 | 11 | 15 | [13, 19] | 15 | 1 | 1 | fallback_marginal |
| 2026-05-30 | 12 | 13 | [12, 17] | 16 | 0 | 1 | conditional |
