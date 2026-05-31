# conditional_calibration_v0 (T-9-3) - Results

**Verdict: KILL**

## Gate summary

- G1 global coverage [0.78,0.86] in >=2/3 splits: False
- G2 het-gate OR regime-cov in band: False (het=False, regime=False)
- G3 width inflation <= +0.5: True
- G4 RPS: n/a (interval-only method)
- G5 causal+reproducible: True

## Per-split results

| split | method | global cov | mean width | het gate | calm cov | non_calm cov |
|-------|--------|-----------|------------|----------|----------|--------------|
| 2023-01-01 | v1.0 baseline | 0.9205 | 4.27 | False | 0.9416 | 0.9123 |
| 2023-01-01 | conditional | 0.9274 | 4.40 | False | 0.9611 | 0.9142 |
| 2024-01-01 | v1.0 baseline | 0.9055 | 4.28 | False | 0.9499 | 0.8888 |
| 2024-01-01 | conditional | 0.9103 | 4.56 | False | 0.9424 | 0.8982 |
| 2025-01-01 | v1.0 baseline | 0.8925 | 3.77 | False | 0.9209 | 0.8796 |
| 2025-01-01 | conditional | 0.9096 | 3.98 | False | 0.9319 | 0.8995 |

## ridge_conformal_minimal (cited)

- 2023: coverage=0.888, width=4.5
- 2024: coverage=0.905, width=5.0
- 2025: coverage=0.858, width=4.0

## Diagnosis (KILL)

- Mean regime coverage: {'calm': 0.9451, 'non_calm': 0.904}
- Over-coverage regime: calm
- Per-CP mean coverage: {'20:00': 0.916, '21:00': 0.9196, '22:00': 0.916, '23:00': 0.9114}
- Worst CP: 21:00
- Note: Structural over-coverage is worst in the 'calm' regime (mean cov 0.9451). BOTH regimes exceed the [0.74,0.86] band; conditioning on calm/non_calm does NOT isolate the slack to one regime. The over-coverage is global and structural. Worst CP: 21:00 (mean cov 0.9196).
- Next candidate: NWP-spread sigma or accept ridge_conformal_minimal as operational stopgap

