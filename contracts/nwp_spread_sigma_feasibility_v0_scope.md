# Scope: nwp_spread_sigma_calibration_v0 - FEASIBILITY FIRST (T-9-6)

> `scope_version = 1.0` (frozen 2026-05-31). Phase 9 calibration. NOT a full calibration commitment -
> this front answers ONE question first: does a causal NWP-spread uncertainty axis even EXIST at the CP
> with enough quality to be worth calibrating on?

## Why feasibility-first

The reviewer flagged the trap: if we condition on NWP-spread but still calibrate decimal->`Q`, we just
repeat the T-9-3 failure on a new axis. So before building any calibrator: produce a FEASIBILITY report.
Only if it passes do we (later, separate prereg) build a calibrator - and it must be integer-native
(per T-9-5), not decimal->`Q`.

## The feasibility question

Is there a causal, CP-available `nwp_spread` signal (ensemble std / model disagreement / lead
uncertainty from the Phase 4 NWP features) that:
1. EXISTS at the operational CP for enough days/splits (coverage of the NWP panel),
2. is genuinely causal (`run_time_utc <= cp_utc - safety_margin`, already enforced in Phase 4 ingest),
3. CORRELATES with the realized integer error `|y_int - pred_int|` (i.e. higher spread -> larger error),
   measured by Spearman correlation + error-by-spread-quartile, walk-forward, on TEST.

## Deliverable (feasibility ONLY)

`reports/calibration/nwp_spread_sigma_feasibility.md` (+ `.json`) +
`scripts/evaluate_nwp_spread_sigma.py` (read-only feasibility eval, no calibrator).

Report: per split, the available NWP-spread columns (reuse `NWP_FEATURE_COLUMNS`:
`nwp_t2m_at_cp_spread_c`, `nwp_disagreement_score`, ...), their CP coverage (fraction of test days
with a non-null causal value), Spearman(spread, |error_int|), and mean |error_int| by spread quartile.

## VERDICT

- **FEASIBLE** if a spread column has CP coverage >= 0.8 of test days AND Spearman with |error_int|
  >= 0.15 (positive) in >= 2/3 splits AND error increases monotonic-ish across spread quartiles. Then
  recommend a follow-up integer-native calibrator conditioned on spread (separate prereg).
- **NOT FEASIBLE** if coverage is thin, or spread does not track error -> do NOT build the calibrator;
  record that the NWP-spread axis is not a usable difficulty signal at NZWN with the current panel.

## Scope

ALLOWED: `scripts/evaluate_nwp_spread_sigma.py` (new, read-only feasibility), `reports/calibration/nwp_spread_sigma_feasibility.{md,json}` (new). Reuse (read-only) the Phase 4 panel + `NWP_FEATURE_COLUMNS`,
`ridge_band`, `eval/metrics`.
FORBIDDEN: `core/cli/decide.py`, `core/decision/**`, Polymarket/odds, execution, any contract change,
building an actual calibrator in this front (feasibility only). No NWP backfill / network calls - use the
existing snapshots; if the panel lacks causal spread for a split, report that honestly as thin coverage.
