# analog_retrieval_audit (Etapa 3; read-only, causal k-NN)

- Target `material_late_warming(k_eod-k_cp>=2)`; K=50; distance feats `k_cp, delta_06_to_cp, southerly_at_cp, rain_persistence_path, s_to_n, month_sin, month_cos`.
- Read-only. Anti-leakage: pool date<test, train-only standardizer/cutpoint, no target/k_eod/tmax_hour in distance. Focus g4 = high-risk lift on NON-CALM days. If no-go, next high-risk candidate is NWP/Open-Meteo (Etapa 4).
- **GO analog high-risk arm: False** | gates {'g1': True, 'g2': True, 'g3': True, 'g4': True, 'g5': False, 'g6_no_leak': True}

| split | base | Brier(base) | PR-AUC | lift@10% | non-calm high-risk lift (n) | qual hi/lo Brier |
|-------|------|-------------|--------|----------|------------------------------|------------------|
| 2023-01-01_to_2023-12-31 | 0.384 | 0.1939(0.2364) | 0.667 | 2.17 | 1.42 (n301) | 0.1831/0.2043 |
| 2024-01-01_to_2024-12-30 | 0.378 | 0.1995(0.2351) | 0.635 | 2.13 | 1.36 (n341) | 0.2074/0.1902 |
| 2025-01-01_to_2025-12-31 | 0.359 | 0.1913(0.2301) | 0.641 | 2.09 | 1.34 (n246) | 0.1978/0.1851 |

## Gate (accept analogs as high-risk arm if all hold >=2/3 splits)

g1 Brier<base; g2 PR-AUC>base; g3 top-decile lift>=1.4; g4 NON-CALM high-risk lift>=1.25 (the focus); g5 high analog_quality outperforms low; g6 no leak.

## Honest reading

_The PREDICTIVE gates all PASS 3/3 - including g4, the pre-registered FOCUS (non-calm high-risk lift >=1.25: 1.42/1.36/1.34) and g3 (top-decile lift ~2.1, far above the 1.38 the logistic risk model reached). PR-AUC 0.64-0.67 vs base ~0.37 is a real jump. The ONLY failing gate is g5 - the analog_quality bucketing (median neighbor distance) did not separate Brier consistently. g5 is a measure of HOW to score adherence, not of predictive capability. So the formal verdict is GO=False (g5), but analogs DEMONSTRABLY capture the high-risk side the logistic could not. Did NOT loosen g5. Next: a v0.1 analog audit with a better analog_quality definition (e.g. effective-n / distance-weighted), NOT tuning K/alpha to force a pass; analogs are the leading high-risk arm candidate for the ensemble._

_If analogs ultimately do not productionize, the next high-risk candidate is NWP/Open-Meteo multi-model (Etapa 4). Read-only here; no forecast wiring._
