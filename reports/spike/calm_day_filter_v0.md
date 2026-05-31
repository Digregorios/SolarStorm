# calm_day_filter_v0 (protective low-risk filter; walk-forward)

- Target `material_late_warming(k_eod-k_cp>=2)`; calm rule: `predicted_risk < train P30`. Protective LOW filter; high-risk detection deferred to Etapa 3 (analogs). Diagnostic only; no forecast/IC/center change. Does not promote risk_model_v0.1.
- **GO accept: True** | gates: {'g1': True, 'g2': True, 'g3': True, 'g4': True, 'g6_no_post_cp_leak': True}

| split | base | c_low | n_calm | calm obs-rate | precision(no-LW) | Brier(base) |
|-------|------|-------|--------|---------------|------------------|-------------|
| 2023-01-01_to_2023-12-31 | 0.384 | 0.378 | 64 | 0.219 | 0.781 | 0.2294(0.2364) |
| 2024-01-01_to_2024-12-30 | 0.378 | 0.314 | 24 | 0.125 | 0.875 | 0.2188(0.2352) |
| 2025-01-01_to_2025-12-31 | 0.359 | 0.255 | 119 | 0.21 | 0.79 | 0.2139(0.2308) |

## Gate (accept if all hold >=2/3 splits)

- g1 calm obs-rate <= 0.65x base; g2 n_calm>=25; g3 precision(no late-warming | calm) >= 0.75; g4 Brier<base; g6 no post-CP leak.

_If accepted, the calm flag may LATER (each separately gated) narrow IC on calm days, reduce late-spike weight, raise persistence/Ridge trust. Nothing changed here._
