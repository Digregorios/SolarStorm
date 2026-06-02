# Onda 2-B: residual serving v0 backtest (CP20-22)

- git_sha: `b6ec9f2b120aa3a67fa124b33dac682b52b27f86`  window: 2024-03-01..2025-12-31 (ECMWF folds)
- seed: 42  n_estimators: 500  calm_tol: 0.05  leakage_ok: **True**
- Backtests the EXACT --serve-residuals decision (ecmwf_residual preferred, gfs_residual otherwise, deterministic Ridge fallback) at CP20-22 over the ECMWF folds. fallback_rate is DESCRIPTIVE (whatever the data is), not tuned. calm_ok uses the same ex-ante strata + 0.05 tolerance as the candidate matrix. Leakage delegated to the frozen select_nwp_v1 (run_time <= cp - safety); a violation raises at panel build, so a clean run is the gate. eval == serving: same PHASE4_FEATURES, max-trajectory anchor, n_estimators, causal climo override.

## Overall (pooled over CP20-22 x folds)

- served ecmwf: 1086  served gfs: 9  ridge fallback: 0 / 1095
- **fallback_rate: 0.0**  calm_ok (all CPs/folds): **True**

### Fallback cross-check vs Onda 2-A audit

- measured (2025 test folds): 0.0
- audit any_causal (2021-2025 full): 0.0444
- Windows DIFFER: this backtest measures the ECMWF overlap TEST folds (2025), the audit measures the full 2021-2025 window. Both recorded; NOT asserted equal -- ECMWF coverage is much higher post-2024.

## Per CP (pooled)

| CP | fallback_rate | served ecmwf | served gfs | ridge fallback | n_test | calm_ok |
|----|---------------|--------------|------------|----------------|--------|---------|
| 20:00 | 0.0 | 362 | 3 | 0 | 365 | True |
| 21:00 | 0.0 | 362 | 3 | 0 | 365 | True |
| 22:00 | 0.0 | 362 | 3 | 0 | 365 | True |

## Per CP x fold (MAE: served vs ridge, ALL + calm)

| CP | fold | fb_rate | served_mae | ridge_mae | served_calm | ridge_calm | calm_ok |
|----|------|---------|------------|-----------|-------------|------------|---------|
| 20:00 | ecmwf-2025H1 | 0.0 | 0.674 | 1.0276 | 0.6 | 0.88 | True |
| 20:00 | ecmwf-2025H2 | 0.0 | 0.5489 | 0.8207 | 0.5517 | 0.9483 | True |
| 21:00 | ecmwf-2025H1 | 0.0 | 0.6685 | 0.9337 | 0.64 | 0.8533 | True |
| 21:00 | ecmwf-2025H2 | 0.0 | 0.5435 | 0.8478 | 0.5 | 0.8621 | True |
| 22:00 | ecmwf-2025H1 | 0.0 | 0.6685 | 0.7735 | 0.64 | 0.7733 | True |
| 22:00 | ecmwf-2025H2 | 0.0 | 0.5761 | 0.7283 | 0.5862 | 0.7586 | True |
