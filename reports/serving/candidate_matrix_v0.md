# T-11-9: Serving Candidate Matrix v0

## Summary

Consolidated comparison of 5 candidate POINT models on identical rows,
walk-forward, per CP and per regime.

- **Prereg:** contracts/serving_candidate_matrix_v0_prereg.md (v1.0)
- **Head-to-head window:** ECMWF overlap 2024-03..2025-12 (2 folds)
- **Context window:** Full 2023-2025 (3 folds, Ridge/GFS/analog only)
- **LGBM n_estimators:** 500 (production default; eval == serving, reviewer P2)
- **Seed:** 42, deterministic=True, num_threads=1
- **Spread excluded:** |GFS-ECMWF| spread NOT used in any routing (T-11-6 FEASIBLE-CONDITIONAL)

## Recommended Routing

| CP | Recommended | Reason |
|----|-------------|--------|
| 20:00 | ecmwf_residual | wins 2/2 folds, no calm regression |
| 21:00 | ecmwf_residual | wins 2/2 folds, no calm regression |
| 22:00 | ecmwf_residual | wins 2/2 folds, no calm regression |
| 23:00 | ridge | best=gfs_residual degrades calm stratum |

**CP20-22 decided SEPARATELY from CP23.** CP23 stays conservative (Ridge/GFS/analog)
unless a candidate wins clearly with no regression and not only on the short window.

## Anti-Winner-Shopping Declaration

- Same rows per comparison (common-date intersection within each split)
- Window differences labelled: ECMWF metrics are 2-fold (2024-03..2025-12);
  full-window metrics are 3-fold (2023-2025). Never compared without noting this.
- No per-split cherry-picking: candidate wins a CP only if it wins >=2/2 folds
  (short window) or >=2/3 folds (full window), NOT one lucky fold.
- CP20-22 rigidly separated from CP23.
- |GFS-ECMWF| spread excluded from all routing logic.

## Head-to-Head Matrix (ECMWF Overlap Window, ALL stratum)

### Split: ecmwf-2025H1 (test 2025-01-01..2025-06-30)

| CP | Candidate | MAE | RMSE | BM | RPS | n |
|----|-----------|-----|------|----|-----|---|
| 20:00 | ridge | 1.0337 | 1.4182 | 0.2921 | 0.9041 | 178 |
| 20:00 | gfs_residual | 0.9663 | 1.2808 | 0.3034 | 0.9141 | 178 |
| 20:00 | ecmwf_residual | 0.6854 | 1.0222 | 0.4551 | 0.6863 | 178 |
| 20:00 | analog_arm | 1.0337 | 1.4182 | 0.2921 | 0.9041 | 178 |
| 20:00 | ensemble | 0.8202 | 1.1367 | 0.3876 | 0.7866 | 178 |
| 21:00 | ridge | 0.9382 | 1.3218 | 0.3427 | 0.8843 | 178 |
| 21:00 | gfs_residual | 1.0169 | 1.3303 | 0.2921 | 0.9397 | 178 |
| 21:00 | ecmwf_residual | 0.6742 | 1.0167 | 0.4663 | 0.6959 | 178 |
| 21:00 | analog_arm | 0.9382 | 1.3218 | 0.3427 | 0.8843 | 178 |
| 21:00 | ensemble | 0.8652 | 1.2316 | 0.3876 | 0.8342 | 178 |
| 22:00 | ridge | 0.7753 | 1.1466 | 0.4326 | 0.7841 | 178 |
| 22:00 | gfs_residual | 1.0506 | 1.4042 | 0.3090 | 0.9711 | 178 |
| 22:00 | ecmwf_residual | 0.6742 | 1.0112 | 0.4663 | 0.6876 | 178 |
| 22:00 | analog_arm | 0.7753 | 1.1466 | 0.4326 | 0.7841 | 178 |
| 22:00 | ensemble | 0.8820 | 1.2654 | 0.3933 | 0.8299 | 178 |
| 23:00 | ridge | 0.6742 | 1.0222 | 0.4663 | 0.6889 | 178 |
| 23:00 | gfs_residual | 0.8989 | 1.2362 | 0.3652 | 0.8831 | 178 |
| 23:00 | ecmwf_residual | 0.6798 | 1.0195 | 0.4663 | 0.6807 | 178 |
| 23:00 | analog_arm | 0.6910 | 1.0359 | 0.4551 | 0.7173 | 178 |
| 23:00 | ensemble | 0.8258 | 1.1922 | 0.3989 | 0.7932 | 178 |

### Split: ecmwf-2025H2 (test 2025-07-01..2025-12-31)

| CP | Candidate | MAE | RMSE | BM | RPS | n |
|----|-----------|-----|------|----|-----|---|
| 20:00 | ridge | 0.8207 | 1.1680 | 0.4185 | 0.6351 | 184 |
| 20:00 | gfs_residual | 0.6087 | 0.9267 | 0.4946 | 0.4324 | 184 |
| 20:00 | ecmwf_residual | 0.5489 | 0.8438 | 0.5272 | 0.4084 | 184 |
| 20:00 | analog_arm | 0.8207 | 1.1680 | 0.4185 | 0.6351 | 184 |
| 20:00 | ensemble | 0.5163 | 0.8042 | 0.5489 | 0.3866 | 184 |
| 21:00 | ridge | 0.8478 | 1.1703 | 0.3750 | 0.5938 | 184 |
| 21:00 | gfs_residual | 0.5707 | 0.8877 | 0.5272 | 0.4186 | 184 |
| 21:00 | ecmwf_residual | 0.5435 | 0.8275 | 0.5272 | 0.4100 | 184 |
| 21:00 | analog_arm | 0.8478 | 1.1703 | 0.3750 | 0.5938 | 184 |
| 21:00 | ensemble | 0.5272 | 0.8042 | 0.5326 | 0.3800 | 184 |
| 22:00 | ridge | 0.7283 | 1.0321 | 0.4076 | 0.5080 | 184 |
| 22:00 | gfs_residual | 0.5761 | 0.8470 | 0.4837 | 0.4170 | 184 |
| 22:00 | ecmwf_residual | 0.5761 | 0.8470 | 0.4891 | 0.4030 | 184 |
| 22:00 | analog_arm | 0.7283 | 1.0321 | 0.4076 | 0.5080 | 184 |
| 22:00 | ensemble | 0.5054 | 0.7697 | 0.5380 | 0.3694 | 184 |
| 23:00 | ridge | 0.6630 | 0.9029 | 0.4076 | 0.4576 | 184 |
| 23:00 | gfs_residual | 0.5924 | 0.8438 | 0.4620 | 0.4134 | 184 |
| 23:00 | ecmwf_residual | 0.5761 | 0.8341 | 0.4837 | 0.3876 | 184 |
| 23:00 | analog_arm | 0.6685 | 0.9059 | 0.4022 | 0.4998 | 184 |
| 23:00 | ensemble | 0.5435 | 0.7940 | 0.5000 | 0.3679 | 184 |

## Regime Breakdown (ECMWF Overlap Window)

### Regime: calm

| CP | Candidate | MAE | RPS | n |
|----|-----------|-----|-----|---|
| 20:00 (ecmwf-2025H1) | ridge | 0.8767 | 1.0338 | 73 |
| 20:00 (ecmwf-2025H1) | gfs_residual | 1.0548 | 1.2298 | 73 |
| 20:00 (ecmwf-2025H1) | ecmwf_residual | 0.6164 | 0.8992 | 73 |
| 20:00 (ecmwf-2025H1) | analog_arm | 0.8767 | 1.0338 | 73 |
| 20:00 (ecmwf-2025H1) | ensemble | 0.9178 | 1.0739 | 73 |
| 21:00 (ecmwf-2025H1) | ridge | 0.8493 | 1.0862 | 73 |
| 21:00 (ecmwf-2025H1) | gfs_residual | 1.0959 | 1.2471 | 73 |
| 21:00 (ecmwf-2025H1) | ecmwf_residual | 0.6438 | 0.9270 | 73 |
| 21:00 (ecmwf-2025H1) | analog_arm | 0.8493 | 1.0862 | 73 |
| 21:00 (ecmwf-2025H1) | ensemble | 0.9726 | 1.1561 | 73 |
| 22:00 (ecmwf-2025H1) | ridge | 0.7671 | 1.0376 | 73 |
| 22:00 (ecmwf-2025H1) | gfs_residual | 1.1507 | 1.3441 | 73 |
| 22:00 (ecmwf-2025H1) | ecmwf_residual | 0.6438 | 0.9114 | 73 |
| 22:00 (ecmwf-2025H1) | analog_arm | 0.7671 | 1.0376 | 73 |
| 22:00 (ecmwf-2025H1) | ensemble | 0.9589 | 1.1536 | 73 |
| 23:00 (ecmwf-2025H1) | ridge | 0.7123 | 1.0031 | 73 |
| 23:00 (ecmwf-2025H1) | gfs_residual | 1.0137 | 1.2413 | 73 |
| 23:00 (ecmwf-2025H1) | ecmwf_residual | 0.6849 | 0.9199 | 73 |
| 23:00 (ecmwf-2025H1) | analog_arm | 0.7123 | 1.0119 | 73 |
| 23:00 (ecmwf-2025H1) | ensemble | 0.8356 | 1.0895 | 73 |
| 20:00 (ecmwf-2025H2) | ridge | 0.9483 | 0.6818 | 58 |
| 20:00 (ecmwf-2025H2) | gfs_residual | 0.6379 | 0.4840 | 58 |
| 20:00 (ecmwf-2025H2) | ecmwf_residual | 0.5517 | 0.4227 | 58 |
| 20:00 (ecmwf-2025H2) | analog_arm | 0.9483 | 0.6818 | 58 |
| 20:00 (ecmwf-2025H2) | ensemble | 0.4828 | 0.3983 | 58 |
| 21:00 (ecmwf-2025H2) | ridge | 0.8621 | 0.5740 | 58 |
| 21:00 (ecmwf-2025H2) | gfs_residual | 0.6034 | 0.4561 | 58 |
| 21:00 (ecmwf-2025H2) | ecmwf_residual | 0.5000 | 0.4148 | 58 |
| 21:00 (ecmwf-2025H2) | analog_arm | 0.8621 | 0.5740 | 58 |
| 21:00 (ecmwf-2025H2) | ensemble | 0.5000 | 0.3903 | 58 |
| 22:00 (ecmwf-2025H2) | ridge | 0.7586 | 0.5016 | 58 |
| 22:00 (ecmwf-2025H2) | gfs_residual | 0.7241 | 0.4854 | 58 |
| 22:00 (ecmwf-2025H2) | ecmwf_residual | 0.5862 | 0.4240 | 58 |
| 22:00 (ecmwf-2025H2) | analog_arm | 0.7586 | 0.5016 | 58 |
| 22:00 (ecmwf-2025H2) | ensemble | 0.5172 | 0.3940 | 58 |
| 23:00 (ecmwf-2025H2) | ridge | 0.5345 | 0.3863 | 58 |
| 23:00 (ecmwf-2025H2) | gfs_residual | 0.6207 | 0.4728 | 58 |
| 23:00 (ecmwf-2025H2) | ecmwf_residual | 0.5690 | 0.3804 | 58 |
| 23:00 (ecmwf-2025H2) | analog_arm | 0.5345 | 0.4251 | 58 |
| 23:00 (ecmwf-2025H2) | ensemble | 0.4828 | 0.3870 | 58 |

### Regime: non_calm

| CP | Candidate | MAE | RPS | n |
|----|-----------|-----|-----|---|
| 20:00 (ecmwf-2025H1) | ridge | 1.1429 | 0.8140 | 105 |
| 20:00 (ecmwf-2025H1) | gfs_residual | 0.9048 | 0.6946 | 105 |
| 20:00 (ecmwf-2025H1) | ecmwf_residual | 0.7333 | 0.5383 | 105 |
| 20:00 (ecmwf-2025H1) | analog_arm | 1.1429 | 0.8140 | 105 |
| 20:00 (ecmwf-2025H1) | ensemble | 0.7524 | 0.5869 | 105 |
| 21:00 (ecmwf-2025H1) | ridge | 1.0000 | 0.7440 | 105 |
| 21:00 (ecmwf-2025H1) | gfs_residual | 0.9619 | 0.7261 | 105 |
| 21:00 (ecmwf-2025H1) | ecmwf_residual | 0.6952 | 0.5352 | 105 |
| 21:00 (ecmwf-2025H1) | analog_arm | 1.0000 | 0.7440 | 105 |
| 21:00 (ecmwf-2025H1) | ensemble | 0.7905 | 0.6104 | 105 |
| 22:00 (ecmwf-2025H1) | ridge | 0.7810 | 0.6079 | 105 |
| 22:00 (ecmwf-2025H1) | gfs_residual | 0.9810 | 0.7117 | 105 |
| 22:00 (ecmwf-2025H1) | ecmwf_residual | 0.6952 | 0.5321 | 105 |
| 22:00 (ecmwf-2025H1) | analog_arm | 0.7810 | 0.6079 | 105 |
| 22:00 (ecmwf-2025H1) | ensemble | 0.8286 | 0.6048 | 105 |
| 23:00 (ecmwf-2025H1) | ridge | 0.6476 | 0.4704 | 105 |
| 23:00 (ecmwf-2025H1) | gfs_residual | 0.8190 | 0.6340 | 105 |
| 23:00 (ecmwf-2025H1) | ecmwf_residual | 0.6762 | 0.5144 | 105 |
| 23:00 (ecmwf-2025H1) | analog_arm | 0.6762 | 0.5125 | 105 |
| 23:00 (ecmwf-2025H1) | ensemble | 0.8190 | 0.5872 | 105 |
| 20:00 (ecmwf-2025H2) | ridge | 0.7619 | 0.6136 | 126 |
| 20:00 (ecmwf-2025H2) | gfs_residual | 0.5952 | 0.4087 | 126 |
| 20:00 (ecmwf-2025H2) | ecmwf_residual | 0.5476 | 0.4018 | 126 |
| 20:00 (ecmwf-2025H2) | analog_arm | 0.7619 | 0.6136 | 126 |
| 20:00 (ecmwf-2025H2) | ensemble | 0.5317 | 0.3812 | 126 |
| 21:00 (ecmwf-2025H2) | ridge | 0.8413 | 0.6028 | 126 |
| 21:00 (ecmwf-2025H2) | gfs_residual | 0.5556 | 0.4013 | 126 |
| 21:00 (ecmwf-2025H2) | ecmwf_residual | 0.5635 | 0.4078 | 126 |
| 21:00 (ecmwf-2025H2) | analog_arm | 0.8413 | 0.6028 | 126 |
| 21:00 (ecmwf-2025H2) | ensemble | 0.5397 | 0.3753 | 126 |
| 22:00 (ecmwf-2025H2) | ridge | 0.7143 | 0.5110 | 126 |
| 22:00 (ecmwf-2025H2) | gfs_residual | 0.5079 | 0.3855 | 126 |
| 22:00 (ecmwf-2025H2) | ecmwf_residual | 0.5714 | 0.3933 | 126 |
| 22:00 (ecmwf-2025H2) | analog_arm | 0.7143 | 0.5110 | 126 |
| 22:00 (ecmwf-2025H2) | ensemble | 0.5000 | 0.3581 | 126 |
| 23:00 (ecmwf-2025H2) | ridge | 0.7222 | 0.4904 | 126 |
| 23:00 (ecmwf-2025H2) | gfs_residual | 0.5794 | 0.3860 | 126 |
| 23:00 (ecmwf-2025H2) | ecmwf_residual | 0.5794 | 0.3910 | 126 |
| 23:00 (ecmwf-2025H2) | analog_arm | 0.7302 | 0.5341 | 126 |
| 23:00 (ecmwf-2025H2) | ensemble | 0.5714 | 0.3591 | 126 |

### Regime: high_delta_06

| CP | Candidate | MAE | RPS | n |
|----|-----------|-----|-----|---|
| 20:00 (ecmwf-2025H1) | ridge | 1.1130 | 0.8213 | 115 |
| 20:00 (ecmwf-2025H1) | gfs_residual | 1.0783 | 0.8330 | 115 |
| 20:00 (ecmwf-2025H1) | ecmwf_residual | 0.7739 | 0.5721 | 115 |
| 20:00 (ecmwf-2025H1) | analog_arm | 1.1130 | 0.8213 | 115 |
| 20:00 (ecmwf-2025H1) | ensemble | 0.8957 | 0.6939 | 115 |
| 21:00 (ecmwf-2025H1) | ridge | 1.0348 | 0.8030 | 115 |
| 21:00 (ecmwf-2025H1) | gfs_residual | 1.1565 | 0.8738 | 115 |
| 21:00 (ecmwf-2025H1) | ecmwf_residual | 0.7565 | 0.5840 | 115 |
| 21:00 (ecmwf-2025H1) | analog_arm | 1.0348 | 0.8030 | 115 |
| 21:00 (ecmwf-2025H1) | ensemble | 0.9739 | 0.7542 | 115 |
| 22:00 (ecmwf-2025H1) | ridge | 0.8870 | 0.6938 | 115 |
| 22:00 (ecmwf-2025H1) | gfs_residual | 1.1826 | 0.8991 | 115 |
| 22:00 (ecmwf-2025H1) | ecmwf_residual | 0.7652 | 0.5690 | 115 |
| 22:00 (ecmwf-2025H1) | analog_arm | 0.8870 | 0.6938 | 115 |
| 22:00 (ecmwf-2025H1) | ensemble | 1.0174 | 0.7519 | 115 |
| 23:00 (ecmwf-2025H1) | ridge | 0.7043 | 0.5440 | 115 |
| 23:00 (ecmwf-2025H1) | gfs_residual | 1.0087 | 0.8048 | 115 |
| 23:00 (ecmwf-2025H1) | ecmwf_residual | 0.7391 | 0.5590 | 115 |
| 23:00 (ecmwf-2025H1) | analog_arm | 0.7304 | 0.5713 | 115 |
| 23:00 (ecmwf-2025H1) | ensemble | 0.9913 | 0.7143 | 115 |
| 20:00 (ecmwf-2025H2) | ridge | 0.7934 | 0.6218 | 121 |
| 20:00 (ecmwf-2025H2) | gfs_residual | 0.5702 | 0.4018 | 121 |
| 20:00 (ecmwf-2025H2) | ecmwf_residual | 0.5620 | 0.4156 | 121 |
| 20:00 (ecmwf-2025H2) | analog_arm | 0.7934 | 0.6218 | 121 |
| 20:00 (ecmwf-2025H2) | ensemble | 0.5207 | 0.3831 | 121 |
| 21:00 (ecmwf-2025H2) | ridge | 0.8347 | 0.6000 | 121 |
| 21:00 (ecmwf-2025H2) | gfs_residual | 0.5289 | 0.3981 | 121 |
| 21:00 (ecmwf-2025H2) | ecmwf_residual | 0.5868 | 0.4200 | 121 |
| 21:00 (ecmwf-2025H2) | analog_arm | 0.8347 | 0.6000 | 121 |
| 21:00 (ecmwf-2025H2) | ensemble | 0.5620 | 0.3802 | 121 |
| 22:00 (ecmwf-2025H2) | ridge | 0.7603 | 0.5187 | 121 |
| 22:00 (ecmwf-2025H2) | gfs_residual | 0.5124 | 0.3787 | 121 |
| 22:00 (ecmwf-2025H2) | ecmwf_residual | 0.5702 | 0.4067 | 121 |
| 22:00 (ecmwf-2025H2) | analog_arm | 0.7603 | 0.5187 | 121 |
| 22:00 (ecmwf-2025H2) | ensemble | 0.4959 | 0.3586 | 121 |
| 23:00 (ecmwf-2025H2) | ridge | 0.7190 | 0.4779 | 121 |
| 23:00 (ecmwf-2025H2) | gfs_residual | 0.5124 | 0.3749 | 121 |
| 23:00 (ecmwf-2025H2) | ecmwf_residual | 0.5537 | 0.3728 | 121 |
| 23:00 (ecmwf-2025H2) | analog_arm | 0.7273 | 0.5338 | 121 |
| 23:00 (ecmwf-2025H2) | ensemble | 0.5289 | 0.3473 | 121 |

### Regime: non_calm_AND_high_delta

| CP | Candidate | MAE | RPS | n |
|----|-----------|-----|-----|---|
| 20:00 (ecmwf-2025H1) | ridge | 1.1667 | 0.8477 | 90 |
| 20:00 (ecmwf-2025H1) | gfs_residual | 0.9556 | 0.7405 | 90 |
| 20:00 (ecmwf-2025H1) | ecmwf_residual | 0.8000 | 0.5817 | 90 |
| 20:00 (ecmwf-2025H1) | analog_arm | 1.1667 | 0.8477 | 90 |
| 20:00 (ecmwf-2025H1) | ensemble | 0.8000 | 0.6320 | 90 |
| 21:00 (ecmwf-2025H1) | ridge | 1.0556 | 0.7859 | 90 |
| 21:00 (ecmwf-2025H1) | gfs_residual | 1.0333 | 0.7795 | 90 |
| 21:00 (ecmwf-2025H1) | ecmwf_residual | 0.7556 | 0.5809 | 90 |
| 21:00 (ecmwf-2025H1) | analog_arm | 1.0556 | 0.7859 | 90 |
| 21:00 (ecmwf-2025H1) | ensemble | 0.8333 | 0.6602 | 90 |
| 22:00 (ecmwf-2025H1) | ridge | 0.8556 | 0.6571 | 90 |
| 22:00 (ecmwf-2025H1) | gfs_residual | 1.0333 | 0.7647 | 90 |
| 22:00 (ecmwf-2025H1) | ecmwf_residual | 0.7556 | 0.5796 | 90 |
| 22:00 (ecmwf-2025H1) | analog_arm | 0.8556 | 0.6571 | 90 |
| 22:00 (ecmwf-2025H1) | ensemble | 0.9111 | 0.6585 | 90 |
| 23:00 (ecmwf-2025H1) | ridge | 0.6444 | 0.4772 | 90 |
| 23:00 (ecmwf-2025H1) | gfs_residual | 0.8778 | 0.6892 | 90 |
| 23:00 (ecmwf-2025H1) | ecmwf_residual | 0.7333 | 0.5602 | 90 |
| 23:00 (ecmwf-2025H1) | analog_arm | 0.6778 | 0.5156 | 90 |
| 23:00 (ecmwf-2025H1) | ensemble | 0.9111 | 0.6400 | 90 |
| 20:00 (ecmwf-2025H2) | ridge | 0.7944 | 0.6344 | 107 |
| 20:00 (ecmwf-2025H2) | gfs_residual | 0.5794 | 0.4066 | 107 |
| 20:00 (ecmwf-2025H2) | ecmwf_residual | 0.5888 | 0.4203 | 107 |
| 20:00 (ecmwf-2025H2) | analog_arm | 0.7944 | 0.6344 | 107 |
| 20:00 (ecmwf-2025H2) | ensemble | 0.5514 | 0.3924 | 107 |
| 21:00 (ecmwf-2025H2) | ridge | 0.8598 | 0.6191 | 107 |
| 21:00 (ecmwf-2025H2) | gfs_residual | 0.5327 | 0.4040 | 107 |
| 21:00 (ecmwf-2025H2) | ecmwf_residual | 0.6168 | 0.4348 | 107 |
| 21:00 (ecmwf-2025H2) | analog_arm | 0.8598 | 0.6191 | 107 |
| 21:00 (ecmwf-2025H2) | ensemble | 0.5701 | 0.3871 | 107 |
| 22:00 (ecmwf-2025H2) | ridge | 0.7383 | 0.5191 | 107 |
| 22:00 (ecmwf-2025H2) | gfs_residual | 0.5047 | 0.3773 | 107 |
| 22:00 (ecmwf-2025H2) | ecmwf_residual | 0.5607 | 0.4026 | 107 |
| 22:00 (ecmwf-2025H2) | analog_arm | 0.7383 | 0.5191 | 107 |
| 22:00 (ecmwf-2025H2) | ensemble | 0.4860 | 0.3552 | 107 |
| 23:00 (ecmwf-2025H2) | ridge | 0.7383 | 0.4901 | 107 |
| 23:00 (ecmwf-2025H2) | gfs_residual | 0.5327 | 0.3734 | 107 |
| 23:00 (ecmwf-2025H2) | ecmwf_residual | 0.5794 | 0.3926 | 107 |
| 23:00 (ecmwf-2025H2) | analog_arm | 0.7477 | 0.5452 | 107 |
| 23:00 (ecmwf-2025H2) | ensemble | 0.5421 | 0.3523 | 107 |

## Full-Window Context (2023-2025, 3 folds, Ridge/GFS/analog only)

NOTE: These metrics cover a LONGER window than the head-to-head above.
Do NOT directly compare a 3-fold metric here against a 2-fold ECMWF metric.

### Split: full-2023 (test 2023-01-01..2023-12-31)

| CP | Candidate | MAE | RMSE | BM | RPS | n |
|----|-----------|-----|------|----|-----|---|
| 20:00 | ridge | 0.9233 | 1.3231 | 0.3836 | 0.7624 | 365 |
| 20:00 | gfs_residual | 0.8000 | 1.1586 | 0.4082 | 0.6650 | 365 |
| 20:00 | analog_arm | 0.9233 | 1.3231 | 0.3836 | 0.7624 | 365 |
| 21:00 | ridge | 0.8301 | 1.1716 | 0.3890 | 0.7032 | 365 |
| 21:00 | gfs_residual | 0.7616 | 1.1299 | 0.4329 | 0.6453 | 365 |
| 21:00 | analog_arm | 0.8301 | 1.1716 | 0.3890 | 0.7032 | 365 |
| 22:00 | ridge | 0.7918 | 1.0816 | 0.3699 | 0.6456 | 365 |
| 22:00 | gfs_residual | 0.7616 | 1.1004 | 0.4164 | 0.6117 | 365 |
| 22:00 | analog_arm | 0.7918 | 1.0816 | 0.3699 | 0.6456 | 365 |
| 23:00 | ridge | 0.6712 | 0.9778 | 0.4575 | 0.5621 | 365 |
| 23:00 | gfs_residual | 0.7014 | 1.0123 | 0.4329 | 0.5784 | 365 |
| 23:00 | analog_arm | 0.6575 | 0.9651 | 0.4658 | 0.5850 | 365 |

### Split: full-2024 (test 2024-01-01..2024-12-31)

| CP | Candidate | MAE | RMSE | BM | RPS | n |
|----|-----------|-----|------|----|-----|---|
| 20:00 | ridge | 1.0164 | 1.3790 | 0.3060 | 0.7436 | 366 |
| 20:00 | gfs_residual | 0.7678 | 1.0725 | 0.3798 | 0.5520 | 366 |
| 20:00 | analog_arm | 1.0164 | 1.3790 | 0.3060 | 0.7436 | 366 |
| 21:00 | ridge | 0.9317 | 1.2814 | 0.3306 | 0.6794 | 366 |
| 21:00 | gfs_residual | 0.7568 | 1.0877 | 0.4044 | 0.5404 | 366 |
| 21:00 | analog_arm | 0.9317 | 1.2814 | 0.3306 | 0.6794 | 366 |
| 22:00 | ridge | 0.7842 | 1.1125 | 0.3934 | 0.5837 | 366 |
| 22:00 | gfs_residual | 0.7131 | 1.0467 | 0.4317 | 0.5045 | 366 |
| 22:00 | analog_arm | 0.7842 | 1.1125 | 0.3934 | 0.5837 | 366 |
| 23:00 | ridge | 0.7022 | 1.0700 | 0.4645 | 0.5214 | 366 |
| 23:00 | gfs_residual | 0.6530 | 1.0149 | 0.4781 | 0.4835 | 366 |
| 23:00 | analog_arm | 0.6885 | 1.0712 | 0.4836 | 0.5460 | 366 |

### Split: full-2025 (test 2025-01-01..2025-12-31)

| CP | Candidate | MAE | RMSE | BM | RPS | n |
|----|-----------|-----|------|----|-----|---|
| 20:00 | ridge | 0.9205 | 1.2431 | 0.3233 | 0.7460 | 365 |
| 20:00 | gfs_residual | 0.7288 | 1.0203 | 0.4164 | 0.6153 | 365 |
| 20:00 | analog_arm | 0.9205 | 1.2431 | 0.3233 | 0.7460 | 365 |
| 21:00 | ridge | 0.8356 | 1.1645 | 0.3781 | 0.7160 | 365 |
| 21:00 | gfs_residual | 0.6493 | 0.9523 | 0.4712 | 0.5675 | 365 |
| 21:00 | analog_arm | 0.8356 | 1.1645 | 0.3781 | 0.7160 | 365 |
| 22:00 | ridge | 0.7452 | 1.0753 | 0.4301 | 0.6361 | 365 |
| 22:00 | gfs_residual | 0.6384 | 0.9609 | 0.4822 | 0.5535 | 365 |
| 22:00 | analog_arm | 0.7452 | 1.0753 | 0.4301 | 0.6361 | 365 |
| 23:00 | ridge | 0.6575 | 0.9422 | 0.4411 | 0.5662 | 365 |
| 23:00 | gfs_residual | 0.6384 | 0.9231 | 0.4575 | 0.5321 | 365 |
| 23:00 | analog_arm | 0.6521 | 0.9334 | 0.4411 | 0.5880 | 365 |

## Notes

- This is a PREDICTOR-ONLY evaluation. No execution, no Polymarket, no calibration.
- The recommended routing is a RECOMMENDATION, not auto-promotion. Actual serving
  wiring is Phase 3 (separate, gated).
- ECMWF-residual and ensemble metrics are on a SHORTER window (2024-03..2025-12,
  2 folds) than Ridge/GFS/analog full-window metrics (2023-2025, 3 folds).
- Analog arm blends on ex-ante non_calm at CP23 only; at CP20-22 it passes through Ridge.
- Ensemble is a per-CP candidate only, NOT a global default (T-11-5 showed it regresses CP23).

