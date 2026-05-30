# Phase 5 - Track D.D1: randomized rounding Q_rand at quantization (one-shot)

- Hypothesis: `trackD_d1_randomized_q` (conformal_method_version `2.0`, q_version `1.1`; pre-reg sha256 `7e14915e6e7b51f7...`)
- Change (exactly one variable): `endpoint quantizer Q -> Q_rand (unbiased randomized rounding)`; seed `20260530`, row_id `sha256(NZWN|date_local|cp_utc)`. Everything else is v1.0.
- Unchanged gates: coverage `0.80 +/- 0.04`; het per-width-quartile in `[0.70, 0.90]` (4 bins); run_id `20260530T135256Z`.

- **ACCEPT D1: False**  (het all splits: False; calib in band: True; widths non-degenerate: True; KILL hit: False)

## Per-width-quartile coverage: BEFORE (v1.0 Q) vs AFTER (D1 Q_rand)

| split | arm | per-bin coverage [w_lo-w_hi] cov (n) | het passed |
|-------|-----|--------------------------------------|------------|
| 2023-01-01_to_2023-12-31 | before | [1-5] 0.821 (n=1333); [6-9] 1.000 (n=98); [10-13] 1.000 (n=18); [14-18] 1.000 (n=11) | False |
| 2023-01-01_to_2023-12-31 | after | [1-5] 0.805 (n=1325); [6-9] 0.990 (n=105); [10-13] 1.000 (n=18); [14-18] 1.000 (n=12) | False |
| 2024-01-01_to_2024-12-30 | before | [1-5] 0.868 (n=1304); [6-10] 0.992 (n=127); [11-15] 1.000 (n=18); [16-21] 1.000 (n=11) | False |
| 2024-01-01_to_2024-12-30 | after | [1-5] 0.858 (n=1300); [6-10] 1.000 (n=128); [11-15] 1.000 (n=21); [16-21] 1.000 (n=11) | False |
| 2025-01-01_to_2025-12-31 | before | [1-3] 0.783 (n=1266); [4-6] 0.988 (n=161); [7-9] 1.000 (n=22); [10-12] 1.000 (n=11) | False |
| 2025-01-01_to_2025-12-31 | after | [1-3] 0.774 (n=1266); [4-5] 0.978 (n=135); [6-8] 1.000 (n=45); [9-11] 1.000 (n=14) | False |

## Global coverage + width non-degeneracy (after) + A/B seed (read-only)

| split | test cov (before->after) | within tol | calib cov | distinct widths | A/B dcov | A/B hi>=lo | assign changed |
|-------|--------------------------|------------|-----------|-----------------|----------|------------|----------------|
| 2023-01-01_to_2023-12-31 | 0.8363 -> 0.8219 | True | 0.8034 | 18 | 0.0062 | True | True |
| 2024-01-01_to_2024-12-30 | 0.8815 -> 0.8740 | False | 0.8000 | 20 | 0.0014 | True | True |
| 2025-01-01_to_2025-12-31 | 0.8103 -> 0.8021 | True | 0.8000 | 11 | 0.0062 | True | True |

## Late-CP stratified coverage (22:00 / 23:00) - AFTER

| split | cp | coverage | mean width | n |
|-------|----|----------|------------|---|
| 2023-01-01_to_2023-12-31 | 22:00 | 0.751 | 3.13 | 365 |
| 2023-01-01_to_2023-12-31 | 23:00 | 0.896 | 4.34 | 365 |
| 2024-01-01_to_2024-12-30 | 22:00 | 0.830 | 3.70 | 365 |
| 2024-01-01_to_2024-12-30 | 23:00 | 0.907 | 4.81 | 365 |
| 2025-01-01_to_2025-12-31 | 22:00 | 0.770 | 2.51 | 365 |
| 2025-01-01_to_2025-12-31 | 23:00 | 0.860 | 3.29 | 365 |

## Notes

- Exactly one variable changed: endpoint quantizer Q -> Q_rand (q_version 1.1).
- Q_rand is unbiased randomized rounding (ceil w.p. frac(x)); seed-fixed, row-local.
- Q_rand formula corrected pre-execution from a biased factor-2 transcription (P(ceil)=2t) to P(ceil)=t; hash re-pinned in the same change-set (see contract).
- het gate is the unchanged binding bar, per split, never pooled.
- A/B seed is read-only evidence (coverage stability + invariants), NOT a gate.
- No seed / Q_rand / floor / c-rule re-tuning after results; a fail opens D2 or a tie-only D1 variant as a NEW pre-registration.
