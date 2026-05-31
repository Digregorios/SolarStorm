# analog_high_risk_arm_v0 (T-9-1) - Evaluation Report

**VERDICT: GO**

CP operational: 23:00
Prereg: contracts/analog_high_risk_arm_v0_prereg.md

## Gates

- G1 noncalm improvement (>=2/3 splits): PASS (3/3)
- G2 aggregate tolerance: PASS
- G3 RPS noncalm: PASS (point-forecast only)
- G4 no leakage: PASS
- G5 reproducible: PASS

## Per-split results

### Split: 2023-01-01_to_2023-12-31
  train=1090 test=365 c30=0.3778 base_rate=0.3789
  noncalm=297 calm=68 lw_truth(DIAG)=140

| stratum | model | MAE | RMSE | BM | n |
|---------|-------|-----|------|----|---|
| all | Ridge | 0.737 | 1.0429 | 0.4192 | 365 |
| all | Arm | 0.7178 | 1.0257 | 0.4301 | 365 |
| noncalm | Ridge | 0.7273 | 1.0445 | 0.4343 | 297 |
| noncalm | Arm | 0.7037 | 1.0233 | 0.4478 | 297 |
| calm | Ridge | 0.7794 | 1.0361 | 0.3529 | 68 |
| calm | Arm | 0.7794 | 1.0361 | 0.3529 | 68 |
| lw_truth_DIAGNOSTIC | Ridge | 0.8214 | 1.168 | 0.4 | 140 |
| lw_truth_DIAGNOSTIC | Arm | 0.8 | 1.1526 | 0.4143 | 140 |

### Split: 2024-01-01_to_2024-12-30
  train=1455 test=365 c30=0.3137 base_rate=0.3801
  noncalm=344 calm=21 lw_truth(DIAG)=138

| stratum | model | MAE | RMSE | BM | n |
|---------|-------|-----|------|----|---|
| all | Ridge | 0.7068 | 1.0803 | 0.4603 | 365 |
| all | Arm | 0.6932 | 1.074 | 0.4767 | 365 |
| noncalm | Ridge | 0.718 | 1.0984 | 0.4593 | 344 |
| noncalm | Arm | 0.7035 | 1.0917 | 0.4767 | 344 |
| calm | Ridge | 0.5238 | 0.7237 | 0.4762 | 21 |
| calm | Arm | 0.5238 | 0.7237 | 0.4762 | 21 |
| lw_truth_DIAGNOSTIC | Ridge | 0.8986 | 1.3513 | 0.3986 | 138 |
| lw_truth_DIAGNOSTIC | Arm | 0.8913 | 1.3486 | 0.413 | 138 |

### Split: 2025-01-01_to_2025-12-31
  train=1821 test=365 c30=0.2381 base_rate=0.3795
  noncalm=280 calm=85 lw_truth(DIAG)=131

| stratum | model | MAE | RMSE | BM | n |
|---------|-------|-----|------|----|---|
| all | Ridge | 0.6575 | 0.9422 | 0.4411 | 365 |
| all | Arm | 0.6521 | 0.9334 | 0.4411 | 365 |
| noncalm | Ridge | 0.7 | 0.9747 | 0.4071 | 280 |
| noncalm | Arm | 0.6929 | 0.9636 | 0.4071 | 280 |
| calm | Ridge | 0.5176 | 0.826 | 0.5529 | 85 |
| calm | Arm | 0.5176 | 0.826 | 0.5529 | 85 |
| lw_truth_DIAGNOSTIC | Ridge | 0.8855 | 1.1851 | 0.3282 | 131 |
| lw_truth_DIAGNOSTIC | Arm | 0.8626 | 1.1689 | 0.3435 | 131 |

## Aggregate (across all splits)

| stratum | model | MAE | BM |
|---------|-------|-----|----|
| all | Ridge | 0.7004 | 0.4402 |
| all | Arm | 0.6877 | 0.4493 |
| noncalm | Ridge | 0.7151 | 0.4336 |
| noncalm | Arm | 0.7000 | 0.4439 |

