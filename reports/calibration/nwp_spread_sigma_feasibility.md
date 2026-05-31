# NWP-Spread Sigma Feasibility Report (T-9-6)

**Verdict: NOT FEASIBLE**

Reason: All spread columns are CONSTANT (zero variance) across all splits. Root cause: panel uses a single NWP model (NCEP GFS only); inter-model spread requires >=2 models but only 1 is available in the local snapshot archive. The NWP-spread axis cannot be evaluated without a multi-model ensemble.

## Criteria

- CP coverage >= 0.8
- Spearman(spread, |error_int|) >= 0.15 (positive)
- Mean |error_int| rises across spread quartiles (Q4 > Q1)
- Required in >= 2/3 splits

## Per-column results

### nwp_t2m_at_cp_spread_c

- Coverage passes: 3/2
- Spearman passes: 0/2
- Monotonic passes: 0/2
- Feasible: False

| split | CP coverage | n_with_spread | Spearman | Q1 err | Q2 err | Q3 err | Q4 err |
|-------|-------------|---------------|----------|--------|--------|--------|--------|
| 2023-01-01_to_2023-12-31 | 1.000 | 365 | - | 0.74 | - | - | - |
| 2024-01-01_to_2024-12-30 | 1.000 | 365 | - | 0.71 | - | - | - |
| 2025-01-01_to_2025-12-31 | 1.000 | 365 | - | 0.66 | - | - | - |

### nwp_disagreement_score

- Coverage passes: 3/2
- Spearman passes: 0/2
- Monotonic passes: 0/2
- Feasible: False

| split | CP coverage | n_with_spread | Spearman | Q1 err | Q2 err | Q3 err | Q4 err |
|-------|-------------|---------------|----------|--------|--------|--------|--------|
| 2023-01-01_to_2023-12-31 | 1.000 | 365 | - | 0.74 | - | - | - |
| 2024-01-01_to_2024-12-30 | 1.000 | 365 | - | 0.71 | - | - | - |
| 2025-01-01_to_2025-12-31 | 1.000 | 365 | - | 0.66 | - | - | - |

### nwp_t2m_maxtraj_spread_c

- Coverage passes: 3/2
- Spearman passes: 0/2
- Monotonic passes: 0/2
- Feasible: False

| split | CP coverage | n_with_spread | Spearman | Q1 err | Q2 err | Q3 err | Q4 err |
|-------|-------------|---------------|----------|--------|--------|--------|--------|
| 2023-01-01_to_2023-12-31 | 1.000 | 365 | - | 0.74 | - | - | - |
| 2024-01-01_to_2024-12-30 | 1.000 | 365 | - | 0.71 | - | - | - |
| 2025-01-01_to_2025-12-31 | 1.000 | 365 | - | 0.66 | - | - | - |

