# Phase 5.1+ Next Steps - Shadow Ops and Promotion Path

Created: 2026-06-03

This plan starts the next project phase after the Shadow Ops readiness patch.
The goal is to move from small reviewer fixes to measurable operational
progress, without enabling automatic trading.

## Wave 0 - Close Phase 5.1

Scope: consolidate Shadow Ops v1 and commit the base.

Deliverables:
- `core/ops/schemas.py`
- `core/ops/shadow_runner.py`
- `scripts/run_shadow_ops_v1.py`
- `scripts/live_shadow_readiness_report.py`
- `contracts/live_shadow_ops_v1_prereg.md`
- `docs/live_shadow_runbook.md`
- unit tests for schema, runner, readiness, and forecast-decision linkage

Gates:
- full suite green
- `git diff --check` clean
- `compileall` clean
- readiness counts only contracted CPs
- leakage uses the causal cutoff `cp_utc - 60min`
- anomaly metrics are visible: `unexpected_cp_records`, `duplicate_cp_records`
- local artifacts and logs are excluded from the commit

## Wave 1 - Shadow Decisions

Objective: extend the forecast runner into a forecast -> decision shadow chain,
while keeping production defaults and real trading unchanged.

Deliverables:
- `ShadowRunnerConfig.with_decisions`
- `core/ops/decision_runner.py` or a narrow extension of `shadow_runner.py`
- `scripts/run_shadow_ops_v1.py --with-decisions`
- `artifacts/shadow_ops/decisions/{date}.jsonl`
- mandatory linkage fields: `forecast_run_id`, `forecast_file`,
  `forecast_model_version`
- readiness odds status by date and CP

Tests:
- decision consumes the forecast JSON probability distribution exactly
- forecast date/CP mismatch fails
- unavailable odds still produce an auditable decision artifact
- decision JSONL is idempotent and repairable
- `--with-decisions` cannot place live orders

## Wave 2 - Live Shadow Window

Objective: collect 7-14 days of live shadow data before any promotion review.

Deliverables:
- `reports/live_shadow/readiness_v1.json`
- `reports/live_shadow/readiness_v1.md`
- `reports/live_shadow/shadow_ops_weekly_v1.md`
- missing date/CP inventory
- fallback distribution by CP and model
- NWP fetch/cache summary by endpoint

Metrics:
- `completeness`
- `leakage_violations`
- `fallback_rate`
- `residual_served_rate_cp20_22`
- `ecmwf_fetch_success`, `gfs_fetch_success`
- `ecmwf_cache_repair`, `gfs_cache_repair`
- `run_age_h_p50`, `run_age_h_p95`
- `valid_time_delta_h_mean`
- `odds_available`, `odds_unavailable`
- `unexpected_cp_records`, `duplicate_cp_records`

## Wave 3 - Promotion Review

Objective: decide whether residual serving can become the operational serving
default. This is not approval for automatic trading.

Deliverables:
- `reports/live_shadow/promotion_review_v1.md`
- checklist against `contracts/live_shadow_ops_v1_prereg.md`
- one of: `KEEP_SHADOW`, `EXTEND_SHADOW`, `PROMOTE_SERVING_DEFAULT`

Promotion gates:
- leakage = 0
- completeness = 1.0 over the frozen window
- all fallback reasons classified
- residual served rate and fallback rate reported without tuning
- no JSON contract regression
- no automatic trading activation

## Parallel Agents

- Agent A: implement `--with-decisions` and decision JSONL.
- Agent B: readiness and promotion reports.
- Agent C: contract, runbook, plan, changelog.
- Agent D: QA, negative tests, full suite, diff-check, compileall, staging audit.

Execution rule: agents may work in parallel within a wave, but commits should
remain small and ordered. Close Wave 0 first, then build Wave 1. Wave 2 starts
only after the runner is stable. Wave 3 starts only after live shadow data
exists.
