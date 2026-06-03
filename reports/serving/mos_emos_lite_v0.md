# Onda 2-C: MOS/EMOS-lite offline evaluator

- status: **read_only_no_serving_change**
- git_sha: `03d59e154a2583002d49ccb516ac89c004c1faa6`
- window: 2024-03-01..2025-12-31  cps: 20:00, 21:00, 22:00
- calib_tail_days: 90  leakage_ok: **True**
- verdict: **NO_PROMOTION**
- Offline readout only. MOS/EMOS-lite centers are fit on fold train excluding the last 90 days; sigma is calibrated on that train-tail; test is read once. NWP causality is delegated to select_max_trajectory_anchor/select_nwp_v1. No routing/default/CLI behavior is changed.

## Gate Summary

| CP | candidate | eligible | RPS | incumbent RPS | MAE | incumbent MAE | calm_ok | calm folds | coverage_ok | folds RPS | folds MAE |
|----|-----------|----------|-----|---------------|-----|---------------|---------|------------|-------------|-----------|-----------|
| 20:00 | mos_ecmwf | False | 0.5812 | 0.5415 | 0.6849 | 0.6109 | False | 0/2 | True | 0/2 | 0/2 |
| 20:00 | emos2_lite | False | 0.6079 | 0.5415 | 0.7151 | 0.6109 | False | 0/2 | True | 0/2 | 0/2 |
| 21:00 | mos_ecmwf | False | 0.5786 | 0.5477 | 0.6548 | 0.6055 | False | 0/2 | True | 0/2 | 1/2 |
| 21:00 | emos2_lite | False | 0.6086 | 0.5477 | 0.7178 | 0.6055 | False | 0/2 | True | 0/2 | 0/2 |
| 22:00 | mos_ecmwf | False | 0.5624 | 0.5401 | 0.6466 | 0.6219 | False | 0/2 | True | 0/2 | 1/2 |
| 22:00 | emos2_lite | False | 0.6085 | 0.5401 | 0.7178 | 0.6219 | False | 0/2 | True | 0/2 | 0/2 |

## Per CP x Fold

| CP | fold | arm | n | engaged_n | coverage | MAE | RPS | BM | IC80 cov | IC80 width | sigma |
|----|------|-----|---|-----------|----------|-----|-----|----|----------|------------|-------|
| 20:00 | ecmwf-2025H1 | ridge | 181 | 181 | 1.0 | 1.116 | 0.9774 | 0.2707 | 0.6906 | 2.768 | None |
| 20:00 | ecmwf-2025H1 | served_v0 | 181 | 181 | 1.0 | 0.674 | 0.6768 | 0.4641 | 0.8508 | 2.6906 | None |
| 20:00 | ecmwf-2025H1 | mos_ecmwf | 181 | 177 | 0.9779 | 0.7735 | 0.7314 | 0.4365 | 0.9116 | 4.0221 | 1.2493 |
| 20:00 | ecmwf-2025H1 | emos2_lite | 181 | 177 | 0.9779 | 0.8343 | 0.7782 | 0.4199 | 0.884 | 4.011 | 1.2476 |
| 20:00 | ecmwf-2025H2 | ridge | 184 | 184 | 1.0 | 0.8261 | 0.6424 | 0.4022 | 0.7663 | 2.712 | None |
| 20:00 | ecmwf-2025H2 | served_v0 | 184 | 184 | 1.0 | 0.5489 | 0.4084 | 0.5272 | 0.9022 | 2.6848 | None |
| 20:00 | ecmwf-2025H2 | mos_ecmwf | 184 | 184 | 1.0 | 0.5978 | 0.4335 | 0.4837 | 0.9511 | 3.4837 | 0.9797 |
| 20:00 | ecmwf-2025H2 | emos2_lite | 184 | 184 | 1.0 | 0.5978 | 0.4403 | 0.4891 | 0.9565 | 3.6141 | 1.0469 |
| 21:00 | ecmwf-2025H1 | ridge | 181 | 181 | 1.0 | 0.9779 | 0.9121 | 0.3315 | 0.7127 | 2.674 | None |
| 21:00 | ecmwf-2025H1 | served_v0 | 181 | 181 | 1.0 | 0.6685 | 0.6877 | 0.4696 | 0.8287 | 2.674 | None |
| 21:00 | ecmwf-2025H1 | mos_ecmwf | 181 | 177 | 0.9779 | 0.768 | 0.7295 | 0.4365 | 0.9116 | 3.9779 | 1.2314 |
| 21:00 | ecmwf-2025H1 | emos2_lite | 181 | 177 | 0.9779 | 0.8398 | 0.7796 | 0.4144 | 0.884 | 4.011 | 1.2476 |
| 21:00 | ecmwf-2025H2 | ridge | 184 | 184 | 1.0 | 0.8261 | 0.5997 | 0.3967 | 0.7826 | 2.6957 | None |
| 21:00 | ecmwf-2025H2 | served_v0 | 184 | 184 | 1.0 | 0.5435 | 0.41 | 0.5272 | 0.9076 | 2.7174 | None |
| 21:00 | ecmwf-2025H2 | mos_ecmwf | 184 | 184 | 1.0 | 0.5435 | 0.4301 | 0.5272 | 0.9565 | 3.6196 | 1.0406 |
| 21:00 | ecmwf-2025H2 | emos2_lite | 184 | 184 | 1.0 | 0.5978 | 0.4403 | 0.4891 | 0.9565 | 3.6141 | 1.0469 |
| 22:00 | ecmwf-2025H1 | ridge | 181 | 181 | 1.0 | 0.8011 | 0.7765 | 0.4199 | 0.768 | 2.6575 | None |
| 22:00 | ecmwf-2025H1 | served_v0 | 181 | 181 | 1.0 | 0.6685 | 0.6794 | 0.4696 | 0.8343 | 2.663 | None |
| 22:00 | ecmwf-2025H1 | mos_ecmwf | 181 | 177 | 0.9779 | 0.7182 | 0.6995 | 0.453 | 0.9171 | 3.9669 | 1.2185 |
| 22:00 | ecmwf-2025H1 | emos2_lite | 181 | 177 | 0.9779 | 0.8398 | 0.7794 | 0.4144 | 0.884 | 4.0055 | 1.2476 |
| 22:00 | ecmwf-2025H2 | ridge | 184 | 184 | 1.0 | 0.75 | 0.5149 | 0.3804 | 0.8587 | 2.7228 | None |
| 22:00 | ecmwf-2025H2 | served_v0 | 184 | 184 | 1.0 | 0.5761 | 0.403 | 0.4891 | 0.9076 | 2.6957 | None |
| 22:00 | ecmwf-2025H2 | mos_ecmwf | 184 | 184 | 1.0 | 0.5761 | 0.4275 | 0.4946 | 0.9674 | 3.75 | 1.0787 |
| 22:00 | ecmwf-2025H2 | emos2_lite | 184 | 184 | 1.0 | 0.5978 | 0.4403 | 0.4891 | 0.9565 | 3.6141 | 1.0469 |
