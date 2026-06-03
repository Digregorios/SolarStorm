# Recent Holdout Failure Diagnosis v1

Diagnostic only. This report reads frozen recent holdout outputs and does not retrain, tune, or promote.

## Executive Summary

| window | n | verdict | emp MAE | best null | delta MAE | fallback rate | conditional rate | p50 mode | p50 mode rate |
|---|---:|---|---:|---|---:|---:|---:|---:|---:|
| recent_holdout_2026-04-01_2026-06-03 | 256 | NULL_NOT_BEATEN | 1.7930 | dminus1 | 0.2774 | 0.7852 | 0.2148 | 15 | 0.4609 |
| recent_holdout_2026-05-01_2026-06-03 | 136 | NULL_NOT_BEATEN | 1.5882 | climatology | 0.1176 | 0.8676 | 0.1324 | 15 | 0.8676 |
| recent_holdout_v1 | 28 | NULL_NOT_BEATEN | 2.3214 | dminus1 | 0.3214 | 0.9286 | 0.0714 | 15 | 0.9286 |

## Findings

### recent_holdout_2026-04-01_2026-06-03

- P0 `empirical_loses_to_null`: {"best_null": "dminus1", "delta_mae": 0.2774, "empirical_mae": 1.793}
- P0 `fallback_marginal_is_negative_value`: {"fallback_best_null": "dminus1", "fallback_delta_mae": 0.4477, "fallback_empirical_mae": 1.9502, "fallback_rate": 0.7852}
- P1 `conditional_signal_exists_but_is_sparse`: {"conditional_best_null": "climatology", "conditional_delta_mae": -0.2545, "conditional_empirical_mae": 1.2182, "conditional_rate": 0.2148}
- P1 `already_reached_regime_should_route_to_t_so_far`: {"empirical_mae": 2.0, "n": 47, "t_so_far_mae": 0.0}
- P1 `late_warming_regime_not_solved_by_empirical_fallback`: {"best_null": "dminus1", "delta_mae": 0.4726, "empirical_mae": 1.8767, "n": 146}

### recent_holdout_2026-05-01_2026-06-03

- P0 `empirical_loses_to_null`: {"best_null": "climatology", "delta_mae": 0.1176, "empirical_mae": 1.5882}
- P0 `fallback_marginal_is_negative_value`: {"fallback_best_null": "climatology", "fallback_delta_mae": 0.2118, "fallback_empirical_mae": 1.661, "fallback_rate": 0.8676}
- P1 `conditional_signal_exists_but_is_sparse`: {"conditional_best_null": "dminus1", "conditional_delta_mae": -0.0556, "conditional_empirical_mae": 1.1111, "conditional_rate": 0.1324}
- P1 `already_reached_regime_should_route_to_t_so_far`: {"empirical_mae": 1.8095, "n": 21, "t_so_far_mae": 0.0}
- P1 `late_warming_regime_not_solved_by_empirical_fallback`: {"best_null": "climatology", "delta_mae": 0.6164, "empirical_mae": 1.7945, "n": 73}
- P1 `empirical_point_forecast_collapse`: {"p50_mode": 15, "p50_mode_rate": 0.8676, "p50_unique_count": 2}

### recent_holdout_v1

- P0 `empirical_loses_to_null`: {"best_null": "dminus1", "delta_mae": 0.3214, "empirical_mae": 2.3214}
- P0 `fallback_marginal_is_negative_value`: {"fallback_best_null": "dminus1", "fallback_delta_mae": 0.3077, "fallback_empirical_mae": 2.3462, "fallback_rate": 0.9286}
- P1 `already_reached_regime_should_route_to_t_so_far`: {"empirical_mae": 2.5, "n": 8, "t_so_far_mae": 0.0}
- P1 `late_warming_regime_not_solved_by_empirical_fallback`: {"best_null": "dminus1", "delta_mae": 0.2778, "empirical_mae": 2.0556, "n": 18}
- P1 `empirical_point_forecast_collapse`: {"p50_mode": 15, "p50_mode_rate": 0.9286, "p50_unique_count": 3}

## Source Breakdown

| window | source | n | emp MAE | best null | delta MAE | p50 mode | p50 mode rate | bucket p50 | eligible rate | IC80 cov | IC80 width |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| recent_holdout_2026-04-01_2026-06-03 | conditional | 55 | 1.2182 | climatology | -0.2545 | 19 | 0.3273 | 34.0000 | 1.0000 | 0.9455 | 5.8000 |
| recent_holdout_2026-04-01_2026-06-03 | fallback_marginal | 201 | 1.9502 | dminus1 | 0.4477 | 15 | 0.5871 | 21.0000 | 0.0000 | 0.8209 | 6.5274 |
| recent_holdout_2026-05-01_2026-06-03 | conditional | 18 | 1.1111 | dminus1 | -0.0556 | 13 | 1.0000 | 35.0000 | 1.0000 | 1.0000 | 7.0000 |
| recent_holdout_2026-05-01_2026-06-03 | fallback_marginal | 118 | 1.6610 | climatology | 0.2118 | 15 | 1.0000 | 21.0000 | 0.0000 | 0.8983 | 6.8983 |
| recent_holdout_v1 | conditional | 2 | 2.0000 | climatology | 0.5000 | 16 | 0.5000 | 31.0000 | 1.0000 | 1.0000 | 5.0000 |
| recent_holdout_v1 | fallback_marginal | 26 | 2.3462 | dminus1 | 0.3077 | 15 | 1.0000 | 18.5000 | 0.0000 | 0.6923 | 6.5385 |

## Empirical Bucket Floor

| window | group | n | n_min | eligible rate | below floor | bucket p10 | bucket p50 | bucket p90 | marginal p50 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| recent_holdout_2026-04-01_2026-06-03 | overall | 256 | 30 | 0.2148 | 0.7852 | 7.0000 | 22.0000 | 34.0000 | 180.0000 |
| recent_holdout_2026-04-01_2026-06-03 | conditional | 55 | 30 | 1.0000 | 0.0000 | 30.0000 | 34.0000 | 37.0000 | 179.0000 |
| recent_holdout_2026-04-01_2026-06-03 | fallback_marginal | 201 | 30 | 0.0000 | 1.0000 | 4.0000 | 21.0000 | 27.0000 | 186.0000 |
| recent_holdout_2026-05-01_2026-06-03 | overall | 136 | 30 | 0.1324 | 0.8676 | 10.0000 | 21.0000 | 34.0000 | 186.0000 |
| recent_holdout_2026-05-01_2026-06-03 | conditional | 18 | 30 | 1.0000 | 0.0000 | 34.0000 | 35.0000 | 37.0000 | 186.0000 |
| recent_holdout_2026-05-01_2026-06-03 | fallback_marginal | 118 | 30 | 0.0000 | 1.0000 | 6.4000 | 21.0000 | 27.0000 | 186.0000 |
| recent_holdout_v1 | overall | 28 | 30 | 0.0714 | 0.9286 | 0.0000 | 19.0000 | 28.3000 | 213.0000 |
| recent_holdout_v1 | conditional | 2 | 30 | 1.0000 | 0.0000 | 30.2000 | 31.0000 | 31.8000 | 213.0000 |
| recent_holdout_v1 | fallback_marginal | 26 | 30 | 0.0000 | 1.0000 | 0.0000 | 18.5000 | 27.0000 | 213.0000 |

## truth-k_cp Buckets

These buckets are post-hoc diagnostics: they use the final truth and are not live-serving signals.

| window | bucket | n | emp MAE | climatology MAE | t_so_far MAE | dminus1 MAE | best null | delta MAE | fallback rate |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| recent_holdout_2026-04-01_2026-06-03 | late_warming_2plus | 146 | 1.8767 | 1.4863 | 3.3082 | 1.4041 | dminus1 | 0.4726 | 0.7740 |
| recent_holdout_2026-04-01_2026-06-03 | plus_1 | 63 | 1.4444 | 1.9683 | 1.0000 | 1.4921 | t_so_far | 0.4444 | 0.7460 |
| recent_holdout_2026-04-01_2026-06-03 | reached_or_cooling_le_0 | 47 | 2.0000 | 2.1064 | 0.0000 | 1.8936 | t_so_far | 2.0000 | 0.8723 |
| recent_holdout_2026-05-01_2026-06-03 | late_warming_2plus | 73 | 1.7945 | 1.1781 | 3.2055 | 1.3562 | climatology | 0.6164 | 0.8630 |
| recent_holdout_2026-05-01_2026-06-03 | plus_1 | 42 | 1.1190 | 1.8095 | 1.0000 | 1.3571 | t_so_far | 0.1190 | 0.8095 |
| recent_holdout_2026-05-01_2026-06-03 | reached_or_cooling_le_0 | 21 | 1.8095 | 1.8095 | 0.0000 | 2.0952 | t_so_far | 1.8095 | 1.0000 |
| recent_holdout_v1 | late_warming_2plus | 18 | 2.0556 | 2.0000 | 3.3333 | 1.7778 | dminus1 | 0.2778 | 0.8889 |
| recent_holdout_v1 | plus_1 | 2 | 4.0000 | 4.0000 | 1.0000 | 2.0000 | t_so_far | 3.0000 | 1.0000 |
| recent_holdout_v1 | reached_or_cooling_le_0 | 8 | 2.5000 | 2.5000 | 0.0000 | 2.5000 | t_so_far | 2.5000 | 1.0000 |

## CP Breakdown

| window | CP | n | emp MAE | best null | delta MAE | fallback rate | p50 mode |
|---|---|---:|---:|---|---:|---:|---:|
| recent_holdout_2026-04-01_2026-06-03 | 20:00 | 64 | 1.8438 | dminus1 | 0.3282 | 0.8281 | 17 |
| recent_holdout_2026-04-01_2026-06-03 | 21:00 | 64 | 1.7812 | dminus1 | 0.2656 | 0.7344 | 15 |
| recent_holdout_2026-04-01_2026-06-03 | 22:00 | 64 | 1.8281 | dminus1 | 0.3125 | 0.7188 | 15 |
| recent_holdout_2026-04-01_2026-06-03 | 23:00 | 64 | 1.7188 | t_so_far | 0.4063 | 0.8594 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 20:00 | 34 | 1.6471 | climatology | 0.1765 | 0.7647 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 21:00 | 34 | 1.5882 | climatology | 0.1176 | 0.7941 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 22:00 | 34 | 1.5294 | climatology | 0.0588 | 0.9118 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 23:00 | 34 | 1.5882 | t_so_far | 0.2647 | 1.0000 | 15 |
| recent_holdout_v1 | 20:00 | 7 | 2.2857 | dminus1 | 0.2857 | 1.0000 | 15 |
| recent_holdout_v1 | 21:00 | 7 | 2.2857 | dminus1 | 0.2857 | 1.0000 | 15 |
| recent_holdout_v1 | 22:00 | 7 | 2.2857 | dminus1 | 0.2857 | 1.0000 | 15 |
| recent_holdout_v1 | 23:00 | 7 | 2.4286 | t_so_far | 0.7143 | 0.7143 | 15 |

## Worst Days By Empirical Delta

| window | date | n | emp MAE | best null | delta MAE | fallback rate | p50 mode |
|---|---|---:|---:|---|---:|---:|---:|
| recent_holdout_2026-04-01_2026-06-03 | 2026-04-22 | 4 | 5.0000 | t_so_far | 5.0000 | 1.0000 | 17 |
| recent_holdout_2026-04-01_2026-06-03 | 2026-06-02 | 4 | 5.0000 | t_so_far | 5.0000 | 1.0000 | 15 |
| recent_holdout_2026-04-01_2026-06-03 | 2026-04-21 | 4 | 5.0000 | t_so_far | 4.0000 | 1.0000 | 17 |
| recent_holdout_2026-04-01_2026-06-03 | 2026-05-08 | 4 | 4.0000 | dminus1 | 4.0000 | 1.0000 | 15 |
| recent_holdout_2026-04-01_2026-06-03 | 2026-06-01 | 4 | 5.0000 | t_so_far | 3.2500 | 1.0000 | 15 |
| recent_holdout_2026-04-01_2026-06-03 | 2026-04-09 | 4 | 4.0000 | dminus1 | 3.0000 | 1.0000 | 17 |
| recent_holdout_2026-04-01_2026-06-03 | 2026-04-20 | 4 | 3.0000 | t_so_far | 3.0000 | 1.0000 | 17 |
| recent_holdout_2026-04-01_2026-06-03 | 2026-04-24 | 4 | 3.0000 | dminus1 | 3.0000 | 1.0000 | 17 |
| recent_holdout_2026-04-01_2026-06-03 | 2026-04-12 | 4 | 2.5000 | dminus1 | 2.5000 | 0.7500 | 17 |
| recent_holdout_2026-04-01_2026-06-03 | 2026-05-11 | 4 | 3.0000 | t_so_far | 2.2500 | 1.0000 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-06-02 | 4 | 5.0000 | t_so_far | 5.0000 | 1.0000 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-05-08 | 4 | 4.0000 | dminus1 | 4.0000 | 1.0000 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-06-01 | 4 | 5.0000 | t_so_far | 3.2500 | 1.0000 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-05-11 | 4 | 3.0000 | t_so_far | 2.2500 | 1.0000 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-05-06 | 4 | 2.0000 | climatology | 2.0000 | 1.0000 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-05-07 | 4 | 4.0000 | climatology | 2.0000 | 1.0000 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-05-09 | 4 | 2.0000 | t_so_far | 2.0000 | 1.0000 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-05-10 | 4 | 4.0000 | dminus1 | 2.0000 | 1.0000 | 15 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-05-12 | 4 | 2.0000 | climatology | 2.0000 | 0.5000 | 13 |
| recent_holdout_2026-05-01_2026-06-03 | 2026-05-27 | 4 | 1.5000 | climatology | 1.5000 | 0.2500 | 13 |
| recent_holdout_v1 | 2026-06-02 | 4 | 5.0000 | t_so_far | 5.0000 | 1.0000 | 15 |
| recent_holdout_v1 | 2026-06-01 | 4 | 5.0000 | t_so_far | 3.2500 | 1.0000 | 15 |
| recent_holdout_v1 | 2026-05-31 | 4 | 3.0000 | dminus1 | 1.0000 | 1.0000 | 15 |
| recent_holdout_v1 | 2026-05-30 | 4 | 1.5000 | climatology | 0.5000 | 0.7500 | 15 |
| recent_holdout_v1 | 2026-05-29 | 4 | 0.0000 | climatology | 0.0000 | 1.0000 | 15 |
| recent_holdout_v1 | 2026-06-03 | 4 | 0.0000 | climatology | 0.0000 | 1.0000 | 15 |
| recent_holdout_v1 | 2026-05-28 | 4 | 1.7500 | climatology | -0.2500 | 0.7500 | 15 |

## Interpretation Contract

- If empirical loses to the best null in the overall table, the current empirical path has no demonstrated forecast value in that window.
- If fallback_marginal is both frequent and worse than nulls, the conditional table is too sparse for live value.
- If t_so_far wins when truth-k_cp <= 0, serving should route that already-reached regime before any ML layer is considered.
- If p50 mode rate is high, point forecasts are collapsing to a seasonal/default bracket rather than responding to live state.
