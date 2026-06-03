# Recent Holdout Backtest v1

- verdict: **NULL_NOT_BEATEN**
- train: 2020-01-01..2026-05-27 (2333 complete days)
- holdout: 2026-05-28..2026-06-03 (7 complete days)
- base obs max: 2026-05-27T23:30:00+00:00
- eval obs max: 2026-06-03T21:00:00+00:00
- best null by MAE: dminus1
- empirical MAE - best null MAE: 0.3214
- empirical fallback_marginal rate: 0.9286

## Overall

| model | n | MAE | RMSE | BM | RPS | IC80 cov | IC80 width |
|---|---:|---:|---:|---:|---:|---:|---:|
| empirical | 28 | 2.3214 | 3.0531 | 0.2857 | 1.9139 | 0.7143 | 6.4286 |
| climatology | 28 | 2.2857 | 3.0237 | 0.2857 | 2.2857 | NA | NA |
| t_so_far | 28 | 2.2143 | 2.8536 | 0.2857 | 2.2143 | NA | NA |
| dminus1 | 28 | 2.0000 | 2.4495 | 0.1429 | 2.0000 | NA | NA |

## Per CP

### CP 20:00

| model | n | MAE | RMSE | BM | RPS |
|---|---:|---:|---:|---:|---:|
| empirical | 7 | 2.2857 | 3.0237 | 0.2857 | 1.8940 |
| climatology | 7 | 2.2857 | 3.0237 | 0.2857 | 2.2857 |
| t_so_far | 7 | 2.5714 | 3.2514 | 0.2857 | 2.5714 |
| dminus1 | 7 | 2.0000 | 2.4495 | 0.1429 | 2.0000 |

### CP 21:00

| model | n | MAE | RMSE | BM | RPS |
|---|---:|---:|---:|---:|---:|
| empirical | 7 | 2.2857 | 3.0237 | 0.2857 | 1.8940 |
| climatology | 7 | 2.2857 | 3.0237 | 0.2857 | 2.2857 |
| t_so_far | 7 | 2.4286 | 3.0000 | 0.2857 | 2.4286 |
| dminus1 | 7 | 2.0000 | 2.4495 | 0.1429 | 2.0000 |

### CP 22:00

| model | n | MAE | RMSE | BM | RPS |
|---|---:|---:|---:|---:|---:|
| empirical | 7 | 2.2857 | 3.0237 | 0.2857 | 1.8940 |
| climatology | 7 | 2.2857 | 3.0237 | 0.2857 | 2.2857 |
| t_so_far | 7 | 2.1429 | 2.7516 | 0.2857 | 2.1429 |
| dminus1 | 7 | 2.0000 | 2.4495 | 0.1429 | 2.0000 |

### CP 23:00

| model | n | MAE | RMSE | BM | RPS |
|---|---:|---:|---:|---:|---:|
| empirical | 7 | 2.4286 | 3.1396 | 0.2857 | 1.9735 |
| climatology | 7 | 2.2857 | 3.0237 | 0.2857 | 2.2857 |
| t_so_far | 7 | 1.7143 | 2.3299 | 0.2857 | 1.7143 |
| dminus1 | 7 | 2.0000 | 2.4495 | 0.1429 | 2.0000 |


## Per Day

| date | best_by_mae | empirical MAE | climatology MAE | t_so_far MAE | dminus1 MAE | empirical BM |
|---|---|---:|---:|---:|---:|---:|
| 2026-05-28 | empirical | 1.7500 | 2.0000 | 2.5000 | 2.0000 | 0.0000 |
| 2026-05-29 | empirical | 0.0000 | 0.0000 | 4.0000 | 2.0000 | 1.0000 |
| 2026-05-30 | climatology | 1.5000 | 1.0000 | 5.0000 | 1.0000 | 0.0000 |
| 2026-05-31 | dminus1 | 3.0000 | 3.0000 | 2.2500 | 2.0000 | 0.0000 |
| 2026-06-01 | t_so_far | 5.0000 | 5.0000 | 1.7500 | 2.0000 | 0.0000 |
| 2026-06-02 | t_so_far | 5.0000 | 5.0000 | 0.0000 | 0.0000 | 0.0000 |
| 2026-06-03 | empirical | 0.0000 | 0.0000 | 0.0000 | 5.0000 | 1.0000 |

## Row Detail

| date | CP | truth | emp | emp_err | source | k_cp | t_so_far_err | dminus1 | dminus1_err | gap_min | IC80 |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|
| 2026-05-28 | 20:00 | 17 | 15 | 2 | fallback_marginal | 14 | 3 | 15 | 2 | 30 | [13,19] |
| 2026-05-28 | 21:00 | 17 | 15 | 2 | fallback_marginal | 14 | 3 | 15 | 2 | 30 | [13,19] |
| 2026-05-28 | 22:00 | 17 | 15 | 2 | fallback_marginal | 15 | 2 | 15 | 2 | 30 | [13,19] |
| 2026-05-28 | 23:00 | 17 | 16 | 1 | conditional | 15 | 2 | 15 | 2 | 30 | [15,18] |
| 2026-05-29 | 20:00 | 15 | 15 | 0 | fallback_marginal | 11 | 4 | 17 | 2 | 30 | [13,19] |
| 2026-05-29 | 21:00 | 15 | 15 | 0 | fallback_marginal | 11 | 4 | 17 | 2 | 30 | [13,19] |
| 2026-05-29 | 22:00 | 15 | 15 | 0 | fallback_marginal | 11 | 4 | 17 | 2 | 30 | [13,19] |
| 2026-05-29 | 23:00 | 15 | 15 | 0 | fallback_marginal | 11 | 4 | 17 | 2 | 30 | [13,19] |
| 2026-05-30 | 20:00 | 16 | 15 | 1 | fallback_marginal | 10 | 6 | 15 | 1 | 30 | [13,19] |
| 2026-05-30 | 21:00 | 16 | 15 | 1 | fallback_marginal | 11 | 5 | 15 | 1 | 30 | [13,19] |
| 2026-05-30 | 22:00 | 16 | 15 | 1 | fallback_marginal | 11 | 5 | 15 | 1 | 30 | [13,19] |
| 2026-05-30 | 23:00 | 16 | 13 | 3 | conditional | 12 | 4 | 15 | 1 | 30 | [12,17] |
| 2026-05-31 | 20:00 | 18 | 15 | 3 | fallback_marginal | 15 | 3 | 16 | 2 | 30 | [13,19] |
| 2026-05-31 | 21:00 | 18 | 15 | 3 | fallback_marginal | 15 | 3 | 16 | 2 | 30 | [13,19] |
| 2026-05-31 | 22:00 | 18 | 15 | 3 | fallback_marginal | 16 | 2 | 16 | 2 | 30 | [13,19] |
| 2026-05-31 | 23:00 | 18 | 15 | 3 | fallback_marginal | 17 | 1 | 16 | 2 | 30 | [13,19] |
| 2026-06-01 | 20:00 | 20 | 15 | 5 | fallback_marginal | 18 | 2 | 18 | 2 | 30 | [12,17] |
| 2026-06-01 | 21:00 | 20 | 15 | 5 | fallback_marginal | 18 | 2 | 18 | 2 | 30 | [12,17] |
| 2026-06-01 | 22:00 | 20 | 15 | 5 | fallback_marginal | 18 | 2 | 18 | 2 | 30 | [12,17] |
| 2026-06-01 | 23:00 | 20 | 15 | 5 | fallback_marginal | 19 | 1 | 18 | 2 | 30 | [12,17] |
| 2026-06-02 | 20:00 | 20 | 15 | 5 | fallback_marginal | 20 | 0 | 20 | 0 | 30 | [12,17] |
| 2026-06-02 | 21:00 | 20 | 15 | 5 | fallback_marginal | 20 | 0 | 20 | 0 | 30 | [12,17] |
| 2026-06-02 | 22:00 | 20 | 15 | 5 | fallback_marginal | 20 | 0 | 20 | 0 | 30 | [12,17] |
| 2026-06-02 | 23:00 | 20 | 15 | 5 | fallback_marginal | 20 | 0 | 20 | 0 | 30 | [12,17] |
| 2026-06-03 | 20:00 | 15 | 15 | 0 | fallback_marginal | 15 | 0 | 20 | 5 | 30 | [12,17] |
| 2026-06-03 | 21:00 | 15 | 15 | 0 | fallback_marginal | 15 | 0 | 20 | 5 | 30 | [12,17] |
| 2026-06-03 | 22:00 | 15 | 15 | 0 | fallback_marginal | 15 | 0 | 20 | 5 | 30 | [12,17] |
| 2026-06-03 | 23:00 | 15 | 15 | 0 | fallback_marginal | 15 | 0 | 20 | 5 | 30 | [12,17] |

## Empirical Bucket Diagnostics

- n_min_bucket: 30
- Row details JSON includes empirical_bucket_n and empirical_marginal_n for each forecast.

## Source Counts

{"conditional": 2, "fallback_marginal": 26}

## Wins By Day MAE

{"climatology": 1, "dminus1": 1, "empirical": 3, "t_so_far": 2}

## Interpretation

This report is deliberately small if the live gap is small. It is useful as a
leakage/freshness/value smoke, not as a promotion-grade sample.
