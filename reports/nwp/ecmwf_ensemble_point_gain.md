# T-11-5: ECMWF Ensemble Point Gain Evaluation

**Verdict: KILL**

- Prereg: `contracts/ecmwf_ensemble_point_gain_v0_prereg.md` (v1.0)
- Window: 2024-03-01 to 2025-12-31 (ECMWF overlap, SHORTER than 2023-2025 point splits)
- Splits: 2 within-window expanding (train from 2024-03)
- LGBM n_estimators: 200 (reduced from 500 for speed)
- Seed: 42, deterministic=True, num_threads=1

## Gate Results (per candidate; GO = simplest candidate passing gates 1-3)

| Candidate | gate1 CP20-22 (splits) | gate2 CP23 no-regress | gate3 pocket (splits) | passes |
|-----------|------------------------|-----------------------|-----------------------|--------|
| ecmwf_residual | True (2/2) | True | False (1/2) | False |
| ensemble | True (2/2) | False | True (2/2) | False |
| (gate4 causal/deterministic: True; gate5 no exec/calib: True) | | | | |

**Kill reason:** No single NWP candidate passes gates 1-3 per-candidate; ECMWF value, if any, is for SPREAD (T-11-6), not the point.

## Per-CP Results (ALL stratum)

### Split: 2025-H1

| CP | Candidate | MAE | RMSE | BM | RPS | n |
|----|-----------|-----|------|----|-----|---|
| 20:00 | ridge | 1.0337 | 1.4182 | 0.2921 | 0.9041 | 178 |
| 20:00 | gfs_residual | 0.9663 | 1.2808 | 0.3034 | 0.9141 | 178 |
| 20:00 | ecmwf_residual | 0.6854 | 1.0222 | 0.4551 | 0.6863 | 178 |
| 20:00 | ensemble | 0.8202 | 1.1367 | 0.3876 | 0.7866 | 178 |
| 21:00 | ridge | 0.9382 | 1.3218 | 0.3427 | 0.8843 | 178 |
| 21:00 | gfs_residual | 1.0169 | 1.3303 | 0.2921 | 0.9397 | 178 |
| 21:00 | ecmwf_residual | 0.6742 | 1.0167 | 0.4663 | 0.6959 | 178 |
| 21:00 | ensemble | 0.8652 | 1.2316 | 0.3876 | 0.8342 | 178 |
| 22:00 | ridge | 0.7753 | 1.1466 | 0.4326 | 0.7841 | 178 |
| 22:00 | gfs_residual | 1.0506 | 1.4042 | 0.3090 | 0.9711 | 178 |
| 22:00 | ecmwf_residual | 0.6742 | 1.0112 | 0.4663 | 0.6876 | 178 |
| 22:00 | ensemble | 0.8820 | 1.2654 | 0.3933 | 0.8299 | 178 |
| 23:00 | ridge | 0.6742 | 1.0222 | 0.4663 | 0.6889 | 178 |
| 23:00 | gfs_residual | 0.8989 | 1.2362 | 0.3652 | 0.8831 | 178 |
| 23:00 | ecmwf_residual | 0.6798 | 1.0195 | 0.4663 | 0.6807 | 178 |
| 23:00 | ensemble | 0.8258 | 1.1922 | 0.3989 | 0.7932 | 178 |

### Split: 2025-H2

| CP | Candidate | MAE | RMSE | BM | RPS | n |
|----|-----------|-----|------|----|-----|---|
| 20:00 | ridge | 0.7989 | 1.1349 | 0.4239 | 0.6311 | 184 |
| 20:00 | gfs_residual | 0.6033 | 0.9119 | 0.4891 | 0.4310 | 184 |
| 20:00 | ecmwf_residual | 0.5543 | 0.8723 | 0.5435 | 0.4191 | 184 |
| 20:00 | ensemble | 0.5272 | 0.8176 | 0.5435 | 0.3898 | 184 |
| 21:00 | ridge | 0.8152 | 1.1325 | 0.3804 | 0.5887 | 184 |
| 21:00 | gfs_residual | 0.5435 | 0.8723 | 0.5543 | 0.4197 | 184 |
| 21:00 | ecmwf_residual | 0.5435 | 0.8341 | 0.5326 | 0.4116 | 184 |
| 21:00 | ensemble | 0.4837 | 0.7626 | 0.5652 | 0.3686 | 184 |
| 22:00 | ridge | 0.7283 | 1.0321 | 0.4076 | 0.5018 | 184 |
| 22:00 | gfs_residual | 0.5761 | 0.8405 | 0.4837 | 0.4091 | 184 |
| 22:00 | ecmwf_residual | 0.5707 | 0.8373 | 0.4891 | 0.4074 | 184 |
| 22:00 | ensemble | 0.4891 | 0.7445 | 0.5435 | 0.3679 | 184 |
| 23:00 | ridge | 0.6685 | 0.9059 | 0.4022 | 0.4523 | 184 |
| 23:00 | gfs_residual | 0.5924 | 0.8502 | 0.4674 | 0.4192 | 184 |
| 23:00 | ecmwf_residual | 0.5761 | 0.8275 | 0.4783 | 0.3863 | 184 |
| 23:00 | ensemble | 0.5435 | 0.8076 | 0.5109 | 0.3692 | 184 |

## Non-calm AND High-delta Pocket

### Split: 2025-H1

| CP | Candidate | MAE | RPS | n |
|----|-----------|-----|-----|---|
| 20:00 | ridge | 1.1667 | 0.8477 | 90 |
| 20:00 | gfs_residual | 0.9556 | 0.7405 | 90 |
| 20:00 | ecmwf_residual | 0.8000 | 0.5817 | 90 |
| 20:00 | ensemble | 0.8000 | 0.6320 | 90 |
| 21:00 | ridge | 1.0556 | 0.7859 | 90 |
| 21:00 | gfs_residual | 1.0333 | 0.7795 | 90 |
| 21:00 | ecmwf_residual | 0.7556 | 0.5809 | 90 |
| 21:00 | ensemble | 0.8333 | 0.6602 | 90 |
| 22:00 | ridge | 0.8556 | 0.6571 | 90 |
| 22:00 | gfs_residual | 1.0333 | 0.7647 | 90 |
| 22:00 | ecmwf_residual | 0.7556 | 0.5796 | 90 |
| 22:00 | ensemble | 0.9111 | 0.6585 | 90 |
| 23:00 | ridge | 0.6444 | 0.4772 | 90 |
| 23:00 | gfs_residual | 0.8778 | 0.6892 | 90 |
| 23:00 | ecmwf_residual | 0.7333 | 0.5602 | 90 |
| 23:00 | ensemble | 0.9111 | 0.6400 | 90 |

### Split: 2025-H2

| CP | Candidate | MAE | RPS | n |
|----|-----------|-----|-----|---|
| 20:00 | ridge | 0.7850 | 0.6316 | 107 |
| 20:00 | gfs_residual | 0.5794 | 0.4097 | 107 |
| 20:00 | ecmwf_residual | 0.6168 | 0.4428 | 107 |
| 20:00 | ensemble | 0.5607 | 0.3990 | 107 |
| 21:00 | ridge | 0.8318 | 0.6141 | 107 |
| 21:00 | gfs_residual | 0.5140 | 0.4056 | 107 |
| 21:00 | ecmwf_residual | 0.6168 | 0.4293 | 107 |
| 21:00 | ensemble | 0.5047 | 0.3688 | 107 |
| 22:00 | ridge | 0.7477 | 0.5150 | 107 |
| 22:00 | gfs_residual | 0.5327 | 0.3733 | 107 |
| 22:00 | ecmwf_residual | 0.5701 | 0.4089 | 107 |
| 22:00 | ensemble | 0.4860 | 0.3564 | 107 |
| 23:00 | ridge | 0.7477 | 0.4854 | 107 |
| 23:00 | gfs_residual | 0.5140 | 0.3769 | 107 |
| 23:00 | ecmwf_residual | 0.5981 | 0.3913 | 107 |
| 23:00 | ensemble | 0.5327 | 0.3530 | 107 |

## Notes

- This is a SHORTER walk-forward than the 2023-2025 point splits due to ECMWF archive start (2024-02).
- Anti-leakage: per-split train-only climatology, c30, P50; causal NWP (run_time <= cp - 60min).
- Regime strata are EX-ANTE (predicted risk, never truth).
- If KILL: ECMWF value may be for SPREAD (T-11-6), not the point forecast.
