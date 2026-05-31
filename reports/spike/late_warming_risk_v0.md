# material_late_warming_risk_model_v0 (Etapa 5; walk-forward, calibrated)

- Model: `late-warming-risk-v0`; target `material_late_warming(k_eod-k_cp>=2)`; CP `23:00`.
- Features (causal, pre-CP): `delta_06_to_cp, southerly_at_cp, rain_persistence_path, month_sin, month_cos`. Calib held-out 120 d (isotonic).
- Usage: DIAGNOSTIC only (prob + risk_bucket); does NOT modify p50 or conformal here.

## Per-split metrics

| split | base | Brier (base) | PR-AUC | ROC-AUC | lift@10% | low/mid/high obs-rate |
|-------|------|--------------|--------|---------|----------|------------------------|
| 2023-01-01_to_2023-12-31 | 0.384 | 0.2294 (0.2364) | 0.467 | 0.558 | 1.38 | 0.222 / 0.411 / 0.8 |
| 2024-01-01_to_2024-12-30 | 0.378 | 0.2188 (0.2352) | 0.548 | 0.663 | 1.62 | 0.125 / 0.335 / 0.583 |
| 2025-01-01_to_2025-12-31 | 0.359 | 0.2139 (0.2308) | 0.505 | 0.67 | 1.39 | 0.279 / 0.37 / 0.564 |

## GO gate (accept v0 only if all pass in >=2/3 splits)

- g1 Brier < base-rate Brier: **True**
- g2 PR-AUC > base rate: **True**
- g3 top-decile lift >= 1.4: **False**
- g4 low bucket <= 0.8x base: **True**
- g5 bucket reliability monotone (low<=mid<=high): **True**
- g6 no post-CP timestamps: **True** (build_features uses ts<cp; unit-tested)

## Verdict: ACCEPT risk_model_v0 = **False**

_If accepted, the next uses are: (1) conditional conformal by PREDICTED risk bucket; (2) upper-tail adjustment conditioned on risk; (3) light center nudge ONLY if it improves RPS/MAE without degrading calm days. None done here - this is a diagnostic detector._
