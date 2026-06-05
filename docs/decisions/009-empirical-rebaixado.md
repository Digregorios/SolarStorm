# ADR-009: Empirical Conditional Baseline (REBAIXADO)

- **Date:** 2026-06-04
- **Status:** Accepted

## Context

The empirical conditional baseline answers a natural question: "Given the temperature at checkpoint CP in month M is K degrees, what was the end-of-day temperature on similar days?" It is a non-parametric estimate of P(Tmax | month, CP, k_cp) from historical counts.

The old Wellington project used a similar approach as a production model, not a baseline. It collapsed: 92.9% of predictions fell back to the marginal distribution, and the p50 mode dominated the output. The model was effectively a constant predictor with a uniform distribution.

The SolarStorm lesson: this is a **baseline only** (REBAIXADO = demoted in Portuguese). It must never serve as a production forecast. Its role is to define "what a naive historical-lookup would predict" -- any production model must beat this.

## Decision

**Empirical conditional distribution P(k_eod | month, CP, k_cp) with Laplace smoothing (alpha=1.0), minimum bucket size (n=30), and a three-tier fallback chain.**

Implemented in `solarstorm/baselines/_empirical.py`:

### Fallback Chain

1. **Conditional:** Look up `(month, CP, k_cp)` in `cond` dictionary. Requires >= 30 historical examples.
2. **Marginal:** Fallback to `(month, CP)` in `marginal` dictionary. Marginalizes over `k_cp`.
3. **Uniform:** Last resort -- uniform distribution over all observed Tmax values.

### Design Details

- `n_min_bucket = 30`: A conditional bucket must have at least 30 historical examples. Fewer than 30 triggers the marginal fallback. This directly addresses the old project's 92.9% fallback rate -- the threshold was too high relative to data density.
- `laplace_alpha = 1.0`: Add-one smoothing across all possible Tmax values. Prevents zero probabilities and provides a principled prior for unseen outcomes.
- `train_window`: Explicitly required (no silent epoch default). The fit must specify which historical period to use.
- `support_k`: The set of all Tmax values observed in the complete dataset, used for Laplace smoothing normalization.
- `predict_dist()` returns both `(distribution, source)` where source is `"conditional"`, `"fallback_marginal"`, or `"uniform"` -- enabling `fallback_rate` tracking.

### Ladder Level

This is **L4** on the baseline ladder -- above L0 (persistence), L1 (dminus1), and L2 (climatology). It captures the conditional structure that simpler baselines miss but remains a purely historical lookup with no physical model.

## Alternatives Considered

1. **Smaller n_min_bucket (e.g., 5):** Use the conditional lookup with fewer examples. Rejected -- the old project showed that sparse buckets produce unstable estimates and p50 collapse (G3 failure).
2. **No Laplace smoothing (alpha=0):** Use raw empirical frequencies. Rejected -- zero probabilities for unobserved Tmax values cause infinite log-loss; Laplace smoothing is the standard fix.
3. **Kernel density estimation:** Smooth the empirical distribution with a kernel. Rejected -- adds complexity and bandwidth tuning without clear benefit for a baseline.
4. **Production use:** Use this as a forecast model. REJECTED -- this is explicitly a baseline only. See the REBAIXADO warning in the source code.

## Consequences

### Enabled
- A principled non-parametric null model that captures CP-conditional structure.
- `fallback_rate` tracking per CP -- reveals how often the conditional lookup is data-limited.
- The three-tier fallback ensures a distribution is always returned, never None.

### Prevents
- The old project's pattern of a collapsed empirical model serving as production.
- Overfitting to sparse (month, CP, k_cp) buckets.
- Silent zero-probability holes in the distribution.

## References

- `solarstorm/baselines/_empirical.py` -- `EmpiricalConditional`, `fit_empirical_conditional()`, `predict_dist()`
- `solarstorm/eval/_gates.py` -- G2 (fallback dominance), G3 (p50 collapse) gates directly address the old project's failure mode
- Old project postmortems: `quarentena/Wellington/` (92.9% fallback rate, p50 collapse)
