# SolarStorm Baseline Leaderboard — 2026-06-05
Window: 2026-05-06 to 2026-06-04

## CP=20:00 (best null: dminus1)
- L0 persistence: MAE=2.36  RMSE=2.95  bias=-2.36  BM=0.11    n=28
- L1 dminus1: MAE=1.57  RMSE=2.10  bias=-0.14  BM=0.18    n=28
- L2 climatology_doy: MAE=1.64  RMSE=2.22  bias=-0.29  BM=0.29    n=28
- L4 empirical_conditional: MAE=7.96  RMSE=8.24  bias=-7.96  BM=0.00  fallback=100%  n=28

## CP=21:00 (best null: dminus1)
- L0 persistence: MAE=2.25  RMSE=2.76  bias=-2.25  BM=0.11    n=28
- L1 dminus1: MAE=1.57  RMSE=2.10  bias=-0.14  BM=0.18    n=28
- L2 climatology_doy: MAE=1.64  RMSE=2.22  bias=-0.29  BM=0.29    n=28
- L4 empirical_conditional: MAE=7.96  RMSE=8.24  bias=-7.96  BM=0.00  fallback=100%  n=28

## CP=22:00 (best null: dminus1)
- L0 persistence: MAE=1.82  RMSE=2.31  bias=-1.82  BM=0.14    n=28
- L1 dminus1: MAE=1.57  RMSE=2.10  bias=-0.14  BM=0.18    n=28
- L2 climatology_doy: MAE=1.64  RMSE=2.22  bias=-0.29  BM=0.29    n=28
- L4 empirical_conditional: MAE=7.96  RMSE=8.24  bias=-7.96  BM=0.00  fallback=100%  n=28

## CP=23:00 (best null: persistence)
- L0 persistence: MAE=1.32  RMSE=1.78  bias=-1.32  BM=0.25    n=28
- L1 dminus1: MAE=1.57  RMSE=2.10  bias=-0.14  BM=0.18    n=28
- L2 climatology_doy: MAE=1.64  RMSE=2.22  bias=-0.29  BM=0.29    n=28
- L4 empirical_conditional: MAE=7.96  RMSE=8.24  bias=-7.96  BM=0.00  fallback=100%  n=28

## Segments
### foehn_nw
- persistence (): MAE=2.14  n=7
- persistence (): MAE=2.14  n=7
- persistence (): MAE=1.86  n=7
- persistence (): MAE=1.14  n=7
- dminus1 (): MAE=1.71  n=7
- dminus1 (): MAE=1.71  n=7
- dminus1 (): MAE=1.71  n=7
- dminus1 (): MAE=1.71  n=7
- climatology_doy (): MAE=2.43  n=7
- climatology_doy (): MAE=2.43  n=7
- climatology_doy (): MAE=2.43  n=7
- climatology_doy (): MAE=2.43  n=7
- empirical_conditional (): MAE=10.43  n=7
- empirical_conditional (): MAE=10.43  n=7
- empirical_conditional (): MAE=10.43  n=7
- empirical_conditional (): MAE=10.43  n=7
### transition
- persistence (): MAE=2.43  n=21
- persistence (): MAE=2.29  n=21
- persistence (): MAE=1.81  n=21
- persistence (): MAE=1.38  n=21
- dminus1 (): MAE=1.52  n=21
- dminus1 (): MAE=1.52  n=21
- dminus1 (): MAE=1.52  n=21
- dminus1 (): MAE=1.52  n=21
- climatology_doy (): MAE=1.38  n=21
- climatology_doy (): MAE=1.38  n=21
- climatology_doy (): MAE=1.38  n=21
- climatology_doy (): MAE=1.38  n=21
- empirical_conditional (): MAE=7.14  n=21
- empirical_conditional (): MAE=7.14  n=21
- empirical_conditional (): MAE=7.14  n=21
- empirical_conditional (): MAE=7.14  n=21

## Gates
### CP=20:00
- **L0_persistence**: 2/5 passed
  - X G1: KILL — model_mae=2.3571 vs best_null_mae=1.5714
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=20:00: loses to null → stay_out
- **L1_dminus1**: 3/5 passed
  - X G1: KILL — model_mae=1.5714 vs best_null_mae=1.5714
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - + G5: OK — CP=20:00: beats null
- **L2_climatology_doy**: 2/5 passed
  - X G1: KILL — model_mae=1.6429 vs best_null_mae=1.5714
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=20:00: loses to null → stay_out
- **L4_empirical_conditional**: 1/5 passed
  - X G1: KILL — model_mae=7.9643 vs best_null_mae=1.5714
  - X G2: NOT_OPERATIONAL — fallback_rate=1.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=20:00: loses to null → stay_out
### CP=21:00
- **L0_persistence**: 2/5 passed
  - X G1: KILL — model_mae=2.2500 vs best_null_mae=1.5714
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=21:00: loses to null → stay_out
- **L1_dminus1**: 3/5 passed
  - X G1: KILL — model_mae=1.5714 vs best_null_mae=1.5714
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - + G5: OK — CP=21:00: beats null
- **L2_climatology_doy**: 2/5 passed
  - X G1: KILL — model_mae=1.6429 vs best_null_mae=1.5714
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=21:00: loses to null → stay_out
- **L4_empirical_conditional**: 1/5 passed
  - X G1: KILL — model_mae=7.9643 vs best_null_mae=1.5714
  - X G2: NOT_OPERATIONAL — fallback_rate=1.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=21:00: loses to null → stay_out
### CP=22:00
- **L0_persistence**: 2/5 passed
  - X G1: KILL — model_mae=1.8214 vs best_null_mae=1.5714
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=22:00: loses to null → stay_out
- **L1_dminus1**: 3/5 passed
  - X G1: KILL — model_mae=1.5714 vs best_null_mae=1.5714
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - + G5: OK — CP=22:00: beats null
- **L2_climatology_doy**: 2/5 passed
  - X G1: KILL — model_mae=1.6429 vs best_null_mae=1.5714
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=22:00: loses to null → stay_out
- **L4_empirical_conditional**: 1/5 passed
  - X G1: KILL — model_mae=7.9643 vs best_null_mae=1.5714
  - X G2: NOT_OPERATIONAL — fallback_rate=1.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=22:00: loses to null → stay_out
### CP=23:00
- **L0_persistence**: 3/5 passed
  - X G1: KILL — model_mae=1.3214 vs best_null_mae=1.3214
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - + G5: OK — CP=23:00: beats null
- **L1_dminus1**: 2/5 passed
  - X G1: KILL — model_mae=1.5714 vs best_null_mae=1.3214
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=23:00: loses to null → stay_out
- **L2_climatology_doy**: 2/5 passed
  - X G1: KILL — model_mae=1.6429 vs best_null_mae=1.3214
  - + G2: OK — fallback_rate=0.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=23:00: loses to null → stay_out
- **L4_empirical_conditional**: 1/5 passed
  - X G1: KILL — model_mae=7.9643 vs best_null_mae=1.3214
  - X G2: NOT_OPERATIONAL — fallback_rate=1.0000
  - + G3: OK — p50_mode_share=0.0000
  - X G4: NOWCAST_SUSPECT — morning CP — skill_ci_lo unavailable; cannot clear anti-nowcaster gate
  - X G5: STAY_OUT — CP=23:00: loses to null → stay_out

## Baseline+Feature Nulls
- feature slope_3h (CP=21:00): MAE=1.04  n=28  corr_diff=0.0268
- feature slope_3h (CP=22:00): MAE=0.96  n=28  corr_diff=0.0166
- feature slope_3h (CP=23:00): MAE=0.79  n=28  corr_diff=0.0001
- feature hours_to_expected_peak (CP=20:00): MAE=1.50  n=28  corr_diff=0.0000
- feature hours_to_expected_peak (CP=21:00): MAE=1.18  n=28  corr_diff=0.0000
- feature hours_to_expected_peak (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature hours_to_expected_peak (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature dewpoint_depression (CP=20:00): MAE=1.50  n=28  corr_diff=0.0000
- feature dewpoint_depression (CP=21:00): MAE=1.29  n=28  corr_diff=-0.0035
- feature dewpoint_depression (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature dewpoint_depression (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature tmax_dminus1 (CP=20:00): MAE=1.50  n=28  corr_diff=0.0000
- feature tmax_dminus1 (CP=21:00): MAE=1.46  n=28  corr_diff=0.0000
- feature tmax_dminus1 (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature tmax_dminus1 (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature tmin_delta_tmax (CP=20:00): MAE=1.39  n=28  corr_diff=-0.0415
- feature tmin_delta_tmax (CP=21:00): MAE=1.00  n=28  corr_diff=0.0244
- feature tmin_delta_tmax (CP=22:00): MAE=1.11  n=28  corr_diff=-0.0248
- feature tmin_delta_tmax (CP=23:00): MAE=0.82  n=28  corr_diff=-0.0110
- feature wind_dir_change_s_to_n (CP=20:00): MAE=1.50  n=28  corr_diff=0.0000
- feature wind_dir_change_s_to_n (CP=21:00): MAE=1.46  n=28  corr_diff=0.0000
- feature wind_dir_change_s_to_n (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature wind_dir_change_s_to_n (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature precip_disruption (CP=20:00): MAE=1.71  n=28  corr_diff=0.0073
- feature precip_disruption (CP=21:00): MAE=1.29  n=28  corr_diff=0.0227
- feature precip_disruption (CP=22:00): MAE=0.93  n=28  corr_diff=0.0200
- feature precip_disruption (CP=23:00): MAE=1.00  n=28  corr_diff=0.0120
- feature tmax_hour_by_regime_month (CP=20:00): MAE=1.50  n=28  corr_diff=0.0000
- feature tmax_hour_by_regime_month (CP=21:00): MAE=1.18  n=28  corr_diff=0.0000
- feature tmax_hour_by_regime_month (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature tmax_hour_by_regime_month (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature cloud_cover_suppression (CP=20:00): MAE=1.04  n=28  corr_diff=0.0944
- feature cloud_cover_suppression (CP=21:00): MAE=1.07  n=28  corr_diff=0.0471
- feature cloud_cover_suppression (CP=22:00): MAE=0.96  n=28  corr_diff=0.0241
- feature cloud_cover_suppression (CP=23:00): MAE=0.75  n=28  corr_diff=0.0187
- feature pressure_trend_3h (CP=21:00): MAE=1.46  n=28  corr_diff=0.0000
- feature pressure_trend_3h (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature pressure_trend_3h (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature foehn_score (CP=20:00): MAE=1.46  n=28  corr_diff=0.0046
- feature foehn_score (CP=21:00): MAE=1.25  n=28  corr_diff=-0.0525
- feature foehn_score (CP=22:00): MAE=1.00  n=28  corr_diff=0.0051
- feature foehn_score (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature late_warming_anomaly (CP=20:00): MAE=1.43  n=28  corr_diff=0.0186
- feature late_warming_anomaly (CP=21:00): MAE=1.18  n=28  corr_diff=-0.0037
- feature late_warming_anomaly (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature late_warming_anomaly (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature warming_rate_06_09 (CP=21:00): MAE=1.04  n=28  corr_diff=0.0268
- feature warming_rate_06_09 (CP=22:00): MAE=0.96  n=28  corr_diff=0.0166
- feature warming_rate_06_09 (CP=23:00): MAE=0.79  n=28  corr_diff=0.0001
- feature nocturnal_plateau_flag (CP=20:00): MAE=1.50  n=28  corr_diff=0.0000
- feature nocturnal_plateau_flag (CP=21:00): MAE=1.46  n=28  corr_diff=0.0000
- feature nocturnal_plateau_flag (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature nocturnal_plateau_flag (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature dewpoint_collapse_rate_3h (CP=21:00): MAE=1.11  n=28  corr_diff=0.0171
- feature dewpoint_collapse_rate_3h (CP=22:00): MAE=0.89  n=28  corr_diff=0.0318
- feature dewpoint_collapse_rate_3h (CP=23:00): MAE=0.79  n=28  corr_diff=-0.0016
- feature prefrontal_warming_window (CP=20:00): MAE=1.50  n=28  corr_diff=0.0000
- feature prefrontal_warming_window (CP=21:00): MAE=1.43  n=28  corr_diff=0.0012
- feature prefrontal_warming_window (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature prefrontal_warming_window (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature nw_sector_not_foehn (CP=20:00): MAE=1.50  n=28  corr_diff=0.0000
- feature nw_sector_not_foehn (CP=21:00): MAE=1.46  n=28  corr_diff=0.0000
- feature nw_sector_not_foehn (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature nw_sector_not_foehn (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000
- feature cloud_base_transparency (CP=20:00): MAE=1.50  n=28  corr_diff=0.0000
- feature cloud_base_transparency (CP=21:00): MAE=1.46  n=28  corr_diff=0.0000
- feature cloud_base_transparency (CP=22:00): MAE=1.04  n=28  corr_diff=0.0000
- feature cloud_base_transparency (CP=23:00): MAE=0.82  n=28  corr_diff=0.0000


Best null varies by CP. 16 aggregated baseline results across 4 CPs.