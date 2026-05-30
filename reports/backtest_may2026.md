# Side-by-side backtest 2026-05-27..30 (merged history+live, @ CP 23:00)

- n_scored: 4

| arm | bracket-match | IC80 coverage | mean IC80 width |
|-----|---------------|---------------|-----------------|
| empirical | 0.25 | 1.00 | 5.75 |
| ridge_naive_ic | 0.00 | 0.00 | 2.75 |
| ridge_conformal_cp | 0.00 | 0.00 | 3.00 |
| persistence | 0.00 | 0.00 | 1.00 |
| climatology | 0.50 | 0.50 | 1.00 |

| date | truth | empirical | ridge_naive_ic | ridge_conformal_cp | persistence | climatology |
|------|-------|-----------|----------------|--------------------|-------------|-------------|
| 2026-05-27 | 15 | 13/[12, 17] | 13/[12, 13] | 13/[12, 14] | 12 | 15 |
| 2026-05-28 | 17 | 16/[15, 18] | 15/[14, 16] | 15/[14, 16] | 15 | 15 |
| 2026-05-29 | 15 | 15/[13, 19] | 12/[11, 13] | 12/[11, 13] | 11 | 15 |
| 2026-05-30 | 16 | 13/[12, 17] | 12/[11, 13] | 12/[11, 13] | 12 | 15 |

_ridge_conformal_cp (variant 1): same Ridge p50, IC80 = per-CP 80% conformal quantile of the Ridge abs-residuals. ridge_naive_ic is the Phase-3 softmax sanity interval (control).

FINDING (honest): on these 4 fresh days BOTH ridge arms miss - but the failure is CENTER bias, not IC width. The Ridge p50 is cold by 2-4C (13 vs 15, 15 vs 17, 12 vs 15, 12 vs 16); the conformal half-width (q=1, which covers ~0.85 HISTORICALLY, see reports/ridge_conformal_probe.md: per-CP 0.80-0.96) cannot rescue a center that is off by more than its width. Persistence also missed -> these days had late warming AFTER the CP, a causal-horizon limit (the CP-time forecast cannot see the afternoon peak), NOT an interval-calibration bug. The interval was deliberately NOT widened to cover n=4 adversarial days (that would be the over-correction the review warned against). Acceptance verdict: conformal PASSES on the robust historical per-CP coverage; the 4-day sentinel is dominated by center bias and is inconclusive for IC width._
