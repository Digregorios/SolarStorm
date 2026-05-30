# Side-by-side backtest 2026-05-27..30 (merged history+live, @ CP 23:00)

- n_scored: 4

| arm | bracket-match | IC80 coverage |
|-----|---------------|---------------|
| empirical | 0.25 | 1.00 |
| ridge | 0.00 | 0.00 |
| persistence | 0.00 | 0.00 |
| climatology | 0.50 | 0.50 |

| date | truth | empirical p50/IC80 | ridge p50/IC80 | persistence | climatology |
|------|-------|--------------------|----------------|-------------|-------------|
| 2026-05-27 | 15 | 13/[12, 17] | 13/[12, 13] | 12 | 15 |
| 2026-05-28 | 17 | 16/[15, 18] | 15/[14, 16] | 15 | 15 |
| 2026-05-29 | 15 | 15/[13, 19] | 12/[11, 13] | 11 | 15 |
| 2026-05-30 | 16 | 13/[12, 17] | 12/[11, 13] | 12 | 15 |

_NOTE: Ridge IC80 is the Phase-3 sanity interval (p50 +/- discrete_ic), NOT conformal; narrow out-of-sample coverage here is expected and is exactly why Ridge is not promoted as default before conformal/coverage validation._
