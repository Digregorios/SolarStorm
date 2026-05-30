# Phase 5 - Track P': quantization margin (distance-to-threshold) as the difficulty axis (one-shot)

- Hypothesis: `trackPprime_quantization_margin_sigma` (conformal_method_version `1.4`; pre-reg sha256 `e4fb58abb8ce63b6...`)
- Change (exactly one variable): `sigma_hat = 0.5 - |frac(y_pred_dec) - 0.5| [quantization margin]` (before: `p50_var`); floored at calib P1. Everything else is v1.0.
- Unchanged gates: coverage `0.80 +/- 0.04`; het per-width-quartile in `[0.70, 0.90]` (4 bins); run_id `20260530T123033Z`.

- **Sanity passed (all splits): False**  (proxy_rejected: True; one_shot_ran: False)
- **ACCEPT P': False**  (het gate passes all splits: False; KILL hit: True)

## MANDATORY pre-run sanity checks (calib-only, per split)

Check (3) FOCUS Spearman is BINDING; n_subset / distinct_err / Kendall tau-b are read-only auditability (tau-b NEVER overrides pass/fail).

| split | global rho | global pass | per-CP distinct ok | 22:00 | 23:00 | focus rho | focus n | err distinct | tau_b (aux) | focus pass | sanity passed |
|-------|-----------|-------------|--------------------|-------|-------|-----------|---------|--------------|-------------|------------|---------------|
| 2023-01-01_to_2023-12-31 | 0.0105 | False | True | 89 | 89 | 0.1010 | 178 | 4 | 0.0795 | True | False |
| 2024-01-01_to_2024-12-30 | -0.0108 | False | True | 90 | 90 | 0.0414 | 180 | 5 | 0.0304 | False | False |
| 2025-01-01_to_2025-12-31 | 0.0009 | False | True | 90 | 90 | 0.0571 | 180 | 4 | 0.0471 | False | False |

## One-shot NOT run (proxy rejected)

At least one split failed a MANDATORY sanity check, so per the pre-registration the single `phase5_evaluate` one-shot was NOT executed. The quantization-margin proxy is rejected on its honest terms; the next step is a DIFFERENT pre-registered hypothesis (a second P', e.g. `1 - max_prob`, or Track D), NOT a re-tuning of this one.

## Notes

- Exactly one variable changed: sigma_hat = 0.5 - |frac(y_pred_dec) - 0.5|.
- Three sanity checks are calib-only, per split, BINDING: a fail rejects the proxy and the one-shot is NOT run (open the next pre-registered hypothesis).
- Focus (22:00/23:00) Spearman is BINDING; Kendall tau-b is AUXILIARY (read-only).
- het gate is the unchanged binding bar, evaluated per split (never pooled).
- ECE is a separate track (C); NOT bundled here (one hypothesis per change-set).
- Track P' is a branch off v1.0 (NOT bundled with A1/A3/P; no RNG).
- No floor/threshold/c-rule re-tuning after results.
