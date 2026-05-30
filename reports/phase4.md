# Phase 4 - NWP residual learning results

- CP operacional: `23:00`
- Splits: 3
- **Acceptance (paired ablation, C2): PASS** (per-CP 1/3, pooled 3/3, need 2); primary delta = `LGBM(obs+NWP) - LGBM(obs-only)`
- **REQ-AUD-2 gates: PASS** (0 violations; corr_diff excluded as diagnostic)
- **Phase 4 ready: True**

## Paired ablation - marginal NWP contribution (operational CP)

_Acceptance isolates the NWP feature+anchor contribution at a FIXED model class (residual LGBM). primary = LGBM(obs+NWP) - LGBM(obs-only); require ci95_low > 0 AND point > 0._

| split | LGBM obs+NWP | LGBM obs-only | primary delta [CI95] | vs Phase3 Ridge [CI95] |
|-------|--------------|---------------|----------------------|------------------------|
| 2023-01-01_to_2023-12-31 | 0.4329 | 0.4082 | +0.0247 [-0.0357, +0.0904] | -0.0110 [-0.0712, +0.0548] |
| 2024-01-01_to_2024-12-30 | 0.4795 | 0.3589 | +0.1205 [+0.0575, +0.1836] | +0.0466 [-0.0137, +0.1068] |
| 2025-01-01_to_2025-12-31 | 0.4575 | 0.4082 | +0.0493 [-0.0137, +0.1069] | +0.0000 [-0.0603, +0.0576] |

## Bracket-match per split (operational CP only)

| split | persistence | climatology | Ridge full | NWP raw | NWP+residual |
|-------|-------------|-------------|------------|---------|--------------|
| 2023-01-01_to_2023-12-31 | 0.2493 | 0.1671 | 0.4438 | 0.0466 | **0.4329** |
| 2024-01-01_to_2024-12-30 | 0.2329 | 0.1644 | 0.4329 | 0.0301 | **0.4795** |
| 2025-01-01_to_2025-12-31 | 0.2822 | 0.1616 | 0.4575 | 0.0685 | **0.4575** |

## Bracket-match pooled across all CPs (statistical power, same model)

| split | n_test | persistence | climatology | Ridge full | obs-only LGBM | NWP+residual | pooled primary delta [CI95] |
|-------|--------|-------------|-------------|------------|---------------|--------------|------------------------------|
| 2023-01-01_to_2023-12-31 | 1460 | 0.1877 | 0.1671 | 0.3199 | 0.3356 | **0.3986** | +0.0630 [+0.0308, +0.0952] |
| 2024-01-01_to_2024-12-30 | 1460 | 0.1486 | 0.1644 | 0.3158 | 0.3185 | **0.4062** | +0.0877 [+0.0555, +0.1185] |
| 2025-01-01_to_2025-12-31 | 1460 | 0.1863 | 0.1616 | 0.3336 | 0.3418 | **0.4205** | +0.0788 [+0.0466, +0.1089] |

## Training-window asymmetry (split-1)

_The GFS `s3_grib` causal anchor exists only from 2021-03-22, so split-1 (test 2023) trains on ~21 months of NWP-anchored rows while later splits train on more. This is a smaller split-1 training set, NOT leakage nor source heterogeneity (the same single GFS anchor feeds every split). All 3 splits still exceed `min_train_days=365`, so the >=2/3 acceptance rule is preserved (no split dropped, no pre-registration amendment, no sha256 recompute)._

| split | train window | n_train (NWP-anchored rows) |
|-------|--------------|------------------------------|
| 2023-01-01_to_2023-12-31 | 2020-01-01..2022-12-31 | 644 |
| 2024-01-01_to_2024-12-30 | 2020-01-01..2023-12-31 | 1009 |
| 2025-01-01_to_2025-12-31 | 2020-01-01..2024-12-31 | 1375 |

## Horizon-degradation curve (skill by CP = lead-to-peak; design 28.6)

_REPORTED diagnostic, NOT a gate (no committed threshold in the pre-registration). Bracket-match by evaluation CP; earlier CP = longer lead to the afternoon Tmax peak. Genuine forward skill = a positive NWP delta that holds hours before the peak and degrades smoothly, not skill that appears only at the latest CP._

| split | CP | n | obs-only | obs+NWP | NWP delta |
|-------|----|---|----------|---------|-----------|
| 2023-01-01_to_2023-12-31 | 20:00 | 365 | 0.2411 | 0.3534 | +0.1123 |
| 2023-01-01_to_2023-12-31 | 21:00 | 365 | 0.3014 | 0.3671 | +0.0658 |
| 2023-01-01_to_2023-12-31 | 22:00 | 365 | 0.3918 | 0.4411 | +0.0493 |
| 2023-01-01_to_2023-12-31 | 23:00 | 365 | 0.4082 | 0.4329 | +0.0247 |
| 2024-01-01_to_2024-12-30 | 20:00 | 365 | 0.2438 | 0.3479 | +0.1041 |
| 2024-01-01_to_2024-12-30 | 21:00 | 365 | 0.2986 | 0.3753 | +0.0767 |
| 2024-01-01_to_2024-12-30 | 22:00 | 365 | 0.3726 | 0.4219 | +0.0493 |
| 2024-01-01_to_2024-12-30 | 23:00 | 365 | 0.3589 | 0.4795 | +0.1205 |
| 2025-01-01_to_2025-12-31 | 20:00 | 365 | 0.2493 | 0.3781 | +0.1288 |
| 2025-01-01_to_2025-12-31 | 21:00 | 365 | 0.3014 | 0.3973 | +0.0959 |
| 2025-01-01_to_2025-12-31 | 22:00 | 365 | 0.4082 | 0.4493 | +0.0411 |
| 2025-01-01_to_2025-12-31 | 23:00 | 365 | 0.4082 | 0.4575 | +0.0493 |

## Anti-nowcaster gates (REQ-AUD-2)

_corr_diff is a **diagnostic monitor** (criterion_version 1.1): computed on anomalies vs the causal per-split climatology and reported, but it does NOT block the verdict._

### Split 2023-01-01_to_2023-12-31

| gate | value | CI95 | threshold | passed |
|------|-------|------|-----------|--------|
| ss_1h | 0.6628 | [+0.5903, +0.7181] | 0.08 | True |
| ss_3h_proxy | 0.6628 | [+0.5903, +0.7181] | 0.1 | True |
| corr_diff | -0.0101 | [-0.0339, +0.0130] | 0.2 | False (diagnostic) |
| coverage_ic80 | 0.8904 | - | |cov-0.8|<0.04 | None |
| i_t_obs | 0.0006 | - | < 0.1 | True |
| counterfactual_same_temp | 0.7848 | - | > 0.7 | True |
| frozen_obs_nwp | - | - | - | True |

### Split 2024-01-01_to_2024-12-30

| gate | value | CI95 | threshold | passed |
|------|-------|------|-----------|--------|
| ss_1h | 0.6923 | [+0.6342, +0.7486] | 0.08 | True |
| ss_3h_proxy | 0.6923 | [+0.6342, +0.7486] | 0.1 | True |
| corr_diff | -0.0188 | [-0.0456, +0.0091] | 0.2 | False (diagnostic) |
| coverage_ic80 | 0.9068 | - | |cov-0.8|<0.04 | None |
| i_t_obs | 0.0007 | - | < 0.1 | True |
| counterfactual_same_temp | 0.8673 | - | > 0.7 | True |
| frozen_obs_nwp | - | - | - | True |

### Split 2025-01-01_to_2025-12-31

| gate | value | CI95 | threshold | passed |
|------|-------|------|-----------|--------|
| ss_1h | 0.7030 | [+0.6390, +0.7562] | 0.08 | True |
| ss_3h_proxy | 0.7030 | [+0.6390, +0.7562] | 0.1 | True |
| corr_diff | 0.0180 | [-0.0009, +0.0375] | 0.2 | False (diagnostic) |
| coverage_ic80 | 0.9151 | - | |cov-0.8|<0.04 | None |
| i_t_obs | 0.0006 | - | < 0.1 | True |
| counterfactual_same_temp | 0.8424 | - | > 0.7 | True |
| frozen_obs_nwp | - | - | - | True |

