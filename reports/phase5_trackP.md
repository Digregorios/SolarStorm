# Phase 5 - Track P: predictive-distribution uncertainty as the difficulty axis (one-shot)

- Hypothesis: `trackP_predictive_uncertainty_sigma` (conformal_method_version `1.3`; pre-reg sha256 `215c29d34d582cf6...`)
- Change (exactly one variable): `sigma_hat = entropy(prob_dist) [shannon nats, raw]` (before: `p50_var`); floored at calib P1. Everything else is v1.0.
- Unchanged gates: coverage `0.80 +/- 0.04`; het per-width-quartile in `[0.70, 0.90]` (4 bins); run_id `20260530T044216Z`.

- **Sanity passed (all splits): False**  (proxy_rejected: True; one_shot_ran: False)
- **ACCEPT P: False**  (het gate passes all splits: False; KILL hit: True)

## MANDATORY pre-run sanity checks (calib-only, per split)

| split | Spearman rho | rho >= min | per-CP distinct ok | 22:00 distinct | 23:00 distinct | sanity passed |
|-------|--------------|------------|--------------------|----------------|----------------|---------------|
| 2023-01-01_to_2023-12-31 | 0.0414 | False | True | 89 | 89 | False |
| 2024-01-01_to_2024-12-30 | 0.0663 | False | True | 90 | 90 | False |
| 2025-01-01_to_2025-12-31 | 0.0049 | False | True | 90 | 90 | False |

## One-shot NOT run (proxy rejected)

At least one split failed a MANDATORY sanity check, so per the pre-registration the single `phase5_evaluate` one-shot was NOT executed. The entropy proxy is rejected on its honest terms; the next step is a DIFFERENT pre-registered hypothesis (Track P'), NOT a re-tuning of this one.

## Notes

- Exactly one variable changed: sigma_hat = entropy(prob_dist); nothing else moved.
- Sanity checks are calib-only, per split, BINDING: a fail rejects the proxy and the one-shot is NOT run (open Track P', new prereg).
- het gate is the unchanged binding bar, evaluated per split (never pooled).
- ECE is a separate track (C); NOT bundled here (one hypothesis per change-set).
- Track P is a branch off v1.0 (NOT bundled with A1 winsorization or A3 Mondrian).
- No floor/threshold/c-rule re-tuning after results.
