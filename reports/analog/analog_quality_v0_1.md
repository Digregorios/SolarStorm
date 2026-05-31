# analog_quality_v0.1 (operationalize g5; retrieval unchanged)

- K=50; metrics tested: `analog_confidence, effective_n, weighted_mean_dist`. Same retrieval as v0 (7-feat distance incl rain_persistence_path - verified code==prereg). Only the adherence metric changes. If a metric passes, analog high-risk arm is eligible for a (separately gated) build. No forecast wiring.
- **chosen analog_quality: analog_confidence** | g5 operationalized: True
- metric_pass: {'analog_confidence': True, 'effective_n': False, 'weighted_mean_dist': False}

## analog_confidence

| split | n hi/lo | Brier hi/lo (g5a) | lift hi/lo (g5b) |
|-------|---------|-------------------|------------------|
| 2023-01-01 | 203/162 | 0.169/0.2251 (True) | 2.22/1.3 (True) |
| 2024-01-01 | 202/163 | 0.1754/0.2293 (True) | 2.25/1.32 (True) |
| 2025-01-01 | 194/171 | 0.1651/0.221 (True) | 2.64/0.98 (True) |

## effective_n

| split | n hi/lo | Brier hi/lo (g5a) | lift hi/lo (g5b) |
|-------|---------|-------------------|------------------|
| 2023-01-01 | 231/134 | 0.1906/0.1996 (True) | 2.15/2.01 (True) |
| 2024-01-01 | 243/122 | 0.2129/0.1727 (False) | 1.98/2.2 (False) |
| 2025-01-01 | 254/111 | 0.1974/0.1773 (False) | 2.12/1.77 (True) |

## weighted_mean_dist

| split | n hi/lo | Brier hi/lo (g5a) | lift hi/lo (g5b) |
|-------|---------|-------------------|------------------|
| 2023-01-01 | 152/213 | 0.1883/0.1979 (True) | 1.91/2.11 (False) |
| 2024-01-01 | 169/196 | 0.2044/0.1952 (False) | 1.56/2.12 (False) |
| 2025-01-01 | 155/210 | 0.1979/0.1864 (False) | 2.09/2.26 (False) |

_g5a Brier(high-q)<=Brier(low-q); g5b within-bucket top-decile lift(high)>=low; accept a metric if both hold >=2/3 splits. Read-only; no forecast change._
