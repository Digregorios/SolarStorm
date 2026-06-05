# Hypothesis Validation Results — 2026-06-05

| id | feature | cp | regime | effect_size | ci_lo | ci_hi | p_value | fdr | passes | gates | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | slope_3h | 20:00 | all | 1.7764 | 1.6708 | 1.8746 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H1 | slope_3h | 21:00 | all | 1.2121 | 1.1499 | 1.2769 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H1 | slope_3h | 22:00 | all | 0.8470 | 0.7971 | 0.8979 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H1 | slope_3h | 23:00 | all | 0.4465 | 0.4096 | 0.4846 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H2 | hours_to_expected_peak | 20:00 | all | 1.3152 | 1.2360 | 1.3910 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H2 | hours_to_expected_peak | 21:00 | all | 1.0837 | 1.0180 | 1.1506 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H2 | hours_to_expected_peak | 22:00 | all | 0.8013 | 0.7472 | 0.8534 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H2 | hours_to_expected_peak | 23:00 | all | 0.4211 | 0.3819 | 0.4574 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H3 | regime_label | 20:00 | all |  |  |  |  | N | N |  | rejected |
| H3 | regime_label | 21:00 | all |  |  |  |  | N | N |  | rejected |
| H3 | regime_label | 22:00 | all |  |  |  |  | N | N |  | rejected |
| H3 | regime_label | 23:00 | all |  |  |  |  | N | N |  | rejected |
| H4 | dewpoint_depression | 20:00 | all | 1.2834 | 1.2020 | 1.3641 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H4 | dewpoint_depression | 21:00 | all | 1.0690 | 1.0027 | 1.1397 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H4 | dewpoint_depression | 22:00 | all | 0.7916 | 0.7364 | 0.8450 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H4 | dewpoint_depression | 23:00 | all | 0.4047 | 0.3667 | 0.4421 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H5 | tmax_dminus1 | 20:00 | all | 1.2846 | 1.2059 | 1.3629 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H5 | tmax_dminus1 | 21:00 | all | 1.0568 | 0.9912 | 1.1253 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H5 | tmax_dminus1 | 22:00 | all | 0.7916 | 0.7375 | 0.8444 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H5 | tmax_dminus1 | 23:00 | all | 0.4009 | 0.3630 | 0.4387 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H6 | tmin_delta_tmax | 20:00 | all | 1.2956 | 1.2143 | 1.3756 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H6 | tmin_delta_tmax | 21:00 | all | 1.0990 | 1.0314 | 1.1711 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H6 | tmin_delta_tmax | 22:00 | all | 0.7910 | 0.7381 | 0.8452 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H6 | tmin_delta_tmax | 23:00 | all | 0.4149 | 0.3761 | 0.4517 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H7 | intraday_regime_change | 20:00 | all |  |  |  |  | N | N |  | rejected |
| H7 | intraday_regime_change | 21:00 | all |  |  |  |  | N | N |  | rejected |
| H7 | intraday_regime_change | 22:00 | all |  |  |  |  | N | N |  | rejected |
| H7 | intraday_regime_change | 23:00 | all |  |  |  |  | N | N |  | rejected |
| H8 | wind_dir_change_s_to_n | 20:00 | all | 1.2893 | 1.2101 | 1.3684 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H8 | wind_dir_change_s_to_n | 21:00 | all | 1.0551 | 0.9909 | 1.1232 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H8 | wind_dir_change_s_to_n | 22:00 | all | 0.7919 | 0.7379 | 0.8446 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H8 | wind_dir_change_s_to_n | 23:00 | all | 0.4011 | 0.3631 | 0.4388 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H9 | day_sequence_pattern | 20:00 | all |  |  |  |  | N | N |  | rejected |
| H9 | day_sequence_pattern | 21:00 | all |  |  |  |  | N | N |  | rejected |
| H9 | day_sequence_pattern | 22:00 | all |  |  |  |  | N | N |  | rejected |
| H9 | day_sequence_pattern | 23:00 | all |  |  |  |  | N | N |  | rejected |
| H10 | precip_disruption | 20:00 | all | 1.4325 | 1.3568 | 1.5104 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H10 | precip_disruption | 21:00 | all | 1.2107 | 1.1477 | 1.2773 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H10 | precip_disruption | 22:00 | all | 0.8357 | 0.7845 | 0.8882 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H10 | precip_disruption | 23:00 | all | 0.4443 | 0.4064 | 0.4814 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H11 | tmax_hour_by_regime_month | 20:00 | all | 1.3152 | 1.2360 | 1.3910 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H11 | tmax_hour_by_regime_month | 21:00 | all | 1.0837 | 1.0180 | 1.1506 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H11 | tmax_hour_by_regime_month | 22:00 | all | 0.8013 | 0.7472 | 0.8534 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H11 | tmax_hour_by_regime_month | 23:00 | all | 0.4211 | 0.3819 | 0.4574 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H12 | cloud_cover_suppression | 20:00 | all | 1.4153 | 1.3381 | 1.4942 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H12 | cloud_cover_suppression | 21:00 | all | 1.1877 | 1.1224 | 1.2568 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H12 | cloud_cover_suppression | 22:00 | all | 0.8213 | 0.7714 | 0.8740 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H12 | cloud_cover_suppression | 23:00 | all | 0.4322 | 0.3936 | 0.4675 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H13 | pressure_trend_3h | 20:00 | all | 1.5748 | 1.4198 | 1.7020 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H13 | pressure_trend_3h | 21:00 | all | 0.7121 | 0.2034 | 1.0870 | 0.005900 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H13 | pressure_trend_3h | 22:00 | all | 0.7631 | 0.6936 | 0.8265 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H13 | pressure_trend_3h | 23:00 | all | 0.3788 | 0.3272 | 0.4256 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H14 | foehn_score | 20:00 | all | 1.2736 | 1.1946 | 1.3523 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H14 | foehn_score | 21:00 | all | 1.0640 | 0.9984 | 1.1344 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H14 | foehn_score | 22:00 | all | 0.7865 | 0.7332 | 0.8415 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H14 | foehn_score | 23:00 | all | 0.4080 | 0.3694 | 0.4474 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H15 | late_warming_anomaly | 20:00 | all | 1.2872 | 1.2080 | 1.3643 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H15 | late_warming_anomaly | 21:00 | all | 1.0742 | 1.0085 | 1.1426 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H15 | late_warming_anomaly | 22:00 | all | 0.7895 | 0.7353 | 0.8428 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H15 | late_warming_anomaly | 23:00 | all | 0.4047 | 0.3667 | 0.4427 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H16 | regime_score_argmax | 20:00 | all |  |  |  |  | N | N |  | rejected |
| H16 | regime_score_argmax | 21:00 | all |  |  |  |  | N | N |  | rejected |
| H16 | regime_score_argmax | 22:00 | all |  |  |  |  | N | N |  | rejected |
| H16 | regime_score_argmax | 23:00 | all |  |  |  |  | N | N |  | rejected |
| H17 | warming_rate_06_09 | 20:00 | all | 1.7764 | 1.6708 | 1.8746 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H17 | warming_rate_06_09 | 21:00 | all | 1.2121 | 1.1499 | 1.2769 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H17 | warming_rate_06_09 | 22:00 | all | 0.8470 | 0.7971 | 0.8979 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H17 | warming_rate_06_09 | 23:00 | all | 0.4430 | 0.4052 | 0.4799 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H18 | nocturnal_plateau_flag | 20:00 | all | 1.2893 | 1.2101 | 1.3684 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H18 | nocturnal_plateau_flag | 21:00 | all | 1.0551 | 0.9909 | 1.1232 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H18 | nocturnal_plateau_flag | 22:00 | all | 0.7919 | 0.7379 | 0.8446 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H18 | nocturnal_plateau_flag | 23:00 | all | 0.4007 | 0.3633 | 0.4388 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H19 | sst_maritime_cap | 20:00 | all |  |  |  |  | N | N |  | BLOCKED |
| H19 | sst_maritime_cap | 21:00 | all |  |  |  |  | N | N |  | BLOCKED |
| H19 | sst_maritime_cap | 22:00 | all |  |  |  |  | N | N |  | BLOCKED |
| H19 | sst_maritime_cap | 23:00 | all |  |  |  |  | N | N |  | BLOCKED |
| H20 | dewpoint_collapse_rate_3h | 20:00 | all | 1.6993 | 1.5883 | 1.7997 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H20 | dewpoint_collapse_rate_3h | 21:00 | all | 1.1329 | 1.0686 | 1.1997 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H20 | dewpoint_collapse_rate_3h | 22:00 | all | 0.8102 | 0.7582 | 0.8635 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H20 | dewpoint_collapse_rate_3h | 23:00 | all | 0.4341 | 0.3941 | 0.4722 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H21 | prefrontal_warming_window | 20:00 | all | 1.2887 | 1.2092 | 1.3682 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H21 | prefrontal_warming_window | 21:00 | all | 1.0551 | 0.9902 | 1.1238 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H21 | prefrontal_warming_window | 22:00 | all | 0.7921 | 0.7382 | 0.8456 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H21 | prefrontal_warming_window | 23:00 | all | 0.4018 | 0.3636 | 0.4400 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H22 | nw_sector_not_foehn | 20:00 | all | 1.2898 | 1.2105 | 1.3687 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H22 | nw_sector_not_foehn | 21:00 | all | 1.0552 | 0.9913 | 1.1231 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H22 | nw_sector_not_foehn | 22:00 | all | 0.7919 | 0.7380 | 0.8447 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H22 | nw_sector_not_foehn | 23:00 | all | 0.4013 | 0.3631 | 0.4397 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H23 | cloud_base_transparency | 20:00 | all | 1.2893 | 1.2101 | 1.3684 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H23 | cloud_base_transparency | 21:00 | all | 1.0551 | 0.9909 | 1.1232 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H23 | cloud_base_transparency | 22:00 | all | 0.7919 | 0.7379 | 0.8446 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |
| H23 | cloud_base_transparency | 23:00 | all | 0.4011 | 0.3631 | 0.4388 | 0.000100 | Y | Y | G1:OK G2:OK G3:OK G4:OK G5:OK | validated |