# Late-warming precursor audit (Etapa 2; read-only, walk-forward)

## 1. Preregistration
- Target (audit-only): `material_late_warming(k_eod-k_cp>=2)`; base rate `0.377` over `2333` days.
- Split protocol: thresholds fit on TRAIN (<test_start), applied on TEST year; lift OOS. Test years 2023/2024/2025.
- Gate: expected-direction lift in >=2/3 splits; lift>= 1.2 (enhance) or <= 0.8 (suppress); n_bucket >= 25/split.
- Terminology: causal-eligible / pre-CP precursors, NOT proven-causal; drying_warming_wind_proxy (not foehn) until mechanism isolated.
- No center model, no conformal-by-bucket here. Features use only obs with ts < CP.

## 5. Single-feature OOS lift (per split) + gate

| feature | want | split lifts (2023/24/25) | n_bucket (per split) | splits passed | GATE |
|---------|------|--------------------------|----------------------|---------------|------|
| wind_quadrant_change_S_to_N | enhance | 1.70 / 1.76 / 1.76 | 20 / 21 / 19 | 0/3 | fail |
| delta_06_to_cp_top_quartile | enhance | 1.46 / 1.49 / 1.46 | 120 / 119 / 105 | 3/3 | PASS |
| wind_quadrant_at_cp_S | suppress | 0.74 / 0.66 / 0.65 | 116 / 101 / 128 | 3/3 | PASS |
| rain_persistence_path | suppress | 0.61 / 0.42 / 0.51 | 47 / 38 / 44 | 3/3 | PASS |
| drying_warming_wind_proxy | enhance | 1.12 / 1.13 / 1.17 | 168 / 190 / 174 | 0/3 | fail |
| t_06_bottom_quartile | enhance | 0.97 / 0.92 / 0.75 | 126 / 107 / 133 | 0/3 | fail |

## 6. Season-stratified lift (descriptive, full history)

| feature | DJF | MAM | JJA | SON |
|---------|-----|-----|-----|-----|
| wind_quadrant_change_S_to_N | 1.51(n20) | 1.71(n51) | 1.62(n20) | 1.87(n18) |
| delta_06_to_cp_top_quartile | 1.07(n231) | 1.51(n192) | 1.97(n169) | 1.38(n185) |
| wind_quadrant_at_cp_S | 0.96(n252) | 0.52(n187) | 0.28(n166) | 0.94(n143) |
| rain_persistence_path | 0.71(n59) | 0.53(n57) | 0.26(n105) | 0.80(n63) |
| drying_warming_wind_proxy | 0.99(n282) | 1.21(n335) | 1.47(n231) | 1.03(n296) |
| t_06_bottom_quartile | 0.91(n225) | 0.74(n176) | 0.54(n184) | 0.67(n190) |

## 9. Passed / failed precursors

- PASSED (3): delta_06_to_cp_top_quartile, wind_quadrant_at_cp_S, rain_persistence_path
- FAILED (3): wind_quadrant_change_S_to_N, drying_warming_wind_proxy, t_06_bottom_quartile

## 10. Recommendation - binary go/no-go for material_late_warming_risk_model_v0

- Primary precursors passing the gate: **3** (of 4: S->N change, delta_06_to_cp, southerly-at-CP, rain-persistence).
- **GO build risk_model_v0: True** (rule: >=2 primary precursors survive walk-forward).

_Note: season-stratified lift is descriptive (full-history); the GATE uses the OOS per-split protocol. Small-n high-lift signals (e.g. S->N) may pass as candidates without being standalone features. No feature promoted to the forecast here._
