# material_late_warming_risk_model_v0.1 (bucket-separation gate)

- Target `material_late_warming(k_eod-k_cp>=2)`; buckets `train-quantile 30/40/30`. v0 stays GO=False diagnostic; this gate measures bucket separation (the intended use). Prefer v0.1a; s_to_n (v0.1b) only earns its place if it clearly beats a on g3/g5.
- **Accepted variant: None** (GO = False)

## v0.1a - gates: {'g1': True, 'g2': True, 'g3': False, 'g4': True, 'g5': True, 'g6': True, 'g7': True, 'g8_no_post_cp_leak': True} -> accept=False

| split | base | Brier(base) | PR-AUC | low/mid/high obs-rate | n low/mid/high |
|-------|------|-------------|--------|------------------------|----------------|
| 2023-01-01_to_2023-12-31 | 0.384 | 0.2294(0.2364) | 0.467 | 0.219/None/0.419 | 64/0/301 |
| 2024-01-01_to_2024-12-30 | 0.378 | 0.2188(0.2352) | 0.548 | 0.125/0.244/0.486 | 24/127/214 |
| 2025-01-01_to_2025-12-31 | 0.359 | 0.2139(0.2308) | 0.505 | 0.21/0.344/0.525 | 119/128/118 |

## v0.1b - gates: {'g1': True, 'g2': True, 'g3': False, 'g4': True, 'g5': True, 'g6': True, 'g7': True, 'g8_no_post_cp_leak': True} -> accept=False

| split | base | Brier(base) | PR-AUC | low/mid/high obs-rate | n low/mid/high |
|-------|------|-------------|--------|------------------------|----------------|
| 2023-01-01_to_2023-12-31 | 0.384 | 0.2318(0.2364) | 0.492 | 0.212/None/0.421 | 66/0/299 |
| 2024-01-01_to_2024-12-30 | 0.378 | 0.2165(0.2352) | 0.561 | 0.147/0.248/0.495 | 34/125/206 |
| 2025-01-01_to_2025-12-31 | 0.359 | 0.21(0.2308) | 0.518 | 0.163/0.349/0.534 | 98/149/118 |

## Gate legend

g1 Brier<base; g2 PR-AUC>base; g3 high>=1.35x base; g4 low<=0.80x base; g5 (high-low)>=0.25; g6 monotone low<=mid<=high; g7 n_high,n_low>=25; g8 no post-CP leak. Accept if ALL hold in >=2/3 splits.

_If accepted, the predicted risk bucket may condition: conformal IC, upper-tail, eventual center nudge - each as its own gated step. v0 remains diagnostic-only regardless._

_Methodological note (not invalidating; for a future v0.2): isotonic-calibrated probabilities produce TIES/steps, so 30/70 quantile cutpoints can land on a large tied mass (e.g. 2023 had an empty mid + huge high bucket). A v0.2 could bucket by the RAW logistic score (rank) and report the isotonic-calibrated probability separately. NOT changed retroactively - this is logged as a hypothesis, not applied here._
