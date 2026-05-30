# Phase 4 pre-registration (criterion_version = 1.1)

> **Frozen 2026-05-29** before running `scripts/phase4_evaluate.py` on the
> re-anchored (NWP_SOURCE_VERSION 1.1) pipeline. Authority: code review
> `references/code-reviews/update.txt`, design 29.4/29.5, REQ-MET-4, REQ-AUD-2.
>
> This document has TEETH. `core/eval/preregistration.py::preregistration_sha256`
> hashes the canonical block delimited by the `<<<PREREG` / `PREREG>>>` markers
> below. `phase4_evaluate` recomputes that hash at runtime and **exits non-zero if
> it differs from `COMMITTED_SHA256`** recorded in `core/eval/preregistration.py`.
> A moving pre-registration is no pre-registration: editing anything between the
> markers WILL fail the evaluator until the committed hash is deliberately updated
> in the same change (a tracked, reviewable act - not a silent drift).

The canonical, hashed content is everything between the two markers. Prose outside
the markers (this header, the rationale notes) is NOT hashed, so it can be clarified
without a version bump. Substance (thresholds, seeds, folds, decision tree) is inside.

<<<PREREG
PHASE4_PREREGISTRATION
criterion_version: 1.1
nwp_source_version: 1.1
frozen_date: 2026-05-29

# --- Seeds (REQ-MOD-6 determinism) ---
seeds:
  python_random: 42
  numpy: 42
  lightgbm.seed: 42
  lightgbm.bagging_seed: 42
  lightgbm.feature_fraction_seed: 42
  lightgbm.drop_seed: 42
  bootstrap_seed: 42
  permutation_seed: 42
threading.omp_num_threads: 1

# --- Fold boundaries (expanding walk-forward; design 29.4) ---
folds.history_start: 2020-01-01
folds.test_length_days: 365
folds.test_starts: [2023-01-01, 2024-01-01, 2025-01-01]
folds.min_train_days: 365
cp_operational_utc: "23:00"
cp_set_utc: ["20:00", "21:00", "22:00", "23:00"]

# --- Frozen thresholds (REQ-AUD-2 surviving gates) ---
gate.ss_1h_min: 0.08
gate.ss_3h_min: 0.10
gate.i_t_obs_max: 0.10
gate.counterfactual_auc_min: 0.70
gate.coverage_tol: 0.04

# --- corr_diff DEMOTION (C3, your Option 2) ---
# corr_diff stays COMPUTED on anomalies (causal per-split climo, same climo base
# for pred/truth/t_now) and is REPORTED, but is EXCLUDED from aud2_passed /
# violations. Its intent is absorbed by i_t_obs + ss(1h/3h) + counterfactual-AUC +
# the lead/horizon-degradation curve.
corr_diff.role: diagnostic_monitor
corr_diff.blocks_verdict: false
corr_diff.still_computed: true
corr_diff.min_reported: 0.20

# --- Acceptance rule (C2, design 29.5): PAIRED ABLATION, not max-over-baselines ---
acceptance.kind: paired_ablation
acceptance.primary: LGBM_obs_plus_nwp_minus_LGBM_obs_only
acceptance.secondary: LGBM_obs_plus_nwp_minus_phase3_obs_only
acceptance.metric: bracket_match_at_p50
acceptance.ci: bootstrap_paired_ci95
acceptance.require: ci95_low_gt_0_and_point_gt_0
acceptance.n_splits_rule: ">=2/3 (or >=2/2 if split-1 dropped)"

# --- Split-1 (2023) treatment (D7) ---
# Real GFS-2023 probe (AWS noaa-gfs-bdp-pds) attempted in T-OPN-5a BEFORE any drop.
# ECMWF Single Runs do not exist pre-2024-03, so a SYMMETRIC 2-model causal ensemble
# for 2023 may be impossible. Only then drop split-1 from the kill criterion and
# propagate the >=2/2 rule downstream. The drop, if taken, is recorded in the report.
split1.probe_gfs_2023: required_before_drop
split1.drop_only_if: symmetric_2model_causal_ensemble_impossible
split1.on_drop.rule: ">=2/2"

# --- Decision tree (verdict -> source) ---
# PASS  := acceptance.require holds in n_splits_rule AND all surviving gates intact.
# FAIL  := otherwise -> Plan B (design 21.7): NWP demoted to feature/confidence
#          provider; proceed to Phases 5/7/8; NWP NOT deleted; NO threshold loosened.
# T-OPN-5a cross-check (contracts/nwp_source.md) decides HFAPI vs SingleRuns source
# on the max-of-trajectory aggregation; criteria 1-3 gate source validity, criterion
# 4 gates split-1 inclusion.
verdict.pass_requires: [acceptance_met, surviving_gates_intact]
verdict.fail_action: plan_b_demote_nwp_proceed_f5_f7_f8
verdict.no_threshold_loosening_after_results: true
PREREG>>>

## Rationale (not hashed)

- **Why teeth.** Without a runtime hash check, a pre-registration is a suggestion.
  The reviewer (update.txt, condition 2) requires the evaluator to FAIL when the
  runtime hash != committed hash, so results can never be quietly produced under a
  silently-edited contract.
- **Why corr_diff is a monitor, not deleted.** Phase 3 failed corr_diff; keeping it
  as a hard gate after re-framing NWP as a feature provider would re-litigate a
  metric whose intent is already covered by the surviving battery. Demotion is a
  versioned amendment (criterion_version 1.1), not a post-hoc loosening - it was
  fixed BEFORE this re-run.
- **Why a paired ablation.** "NWP+residual beats max(persistence, climo, ridge)"
  compares heterogeneous models and can pass for the wrong reason. The paired
  `LGBM(obs)` vs `LGBM(obs+NWP)` ablation isolates the marginal NWP contribution at
  the same model class; CI95 lo>0 is the honest bar.
- **Why split-1 may drop.** ECMWF Single Runs start 2024-03; a causal 2-model
  ensemble for 2023 needs a real GFS-2023 source. We probe it for real first; only a
  genuine impossibility justifies the >=2/2 fallback, and that is recorded.
