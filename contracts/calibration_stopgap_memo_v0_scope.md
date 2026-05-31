# Decision memo: calibration stopgap (2026-05-31) - T-9-7

> `memo_version = 1.0`. Operational decision while the calibration "roof" stays open. NOT a claim of
> passed calibration. This memo is filled/confirmed by the T-9-7 agent against the live numbers.

## Context

Phase 5 CLOSED NOT READY (REQ-AUD-5 het gate never passed); T-9-3 regime-conditional conformal KILL
(over-coverage is global/structural). The project needs a HONEST operational answer to: "until the
roof is built, which interval may be shown, and under what fences?" - so it is not blocked indefinitely
on perfect calibration.

## Stopgap candidate

`ridge_conformal_minimal` (per-CP IC80 = 80% quantile of the Ridge's own integer abs-residuals;
`reports/ridge_conformal_probe.md`). Observed per-CP coverage 0.86-0.91 (over-covers; honest about it).

## What this memo must state (filled by the agent against current reports)

1. The stopgap IC is **DIAGNOSTIC ONLY**, explicitly NOT "passed conditional calibration" (REQ-AUD-5
   still red). It over-covers (~0.86-0.91); intervals are conservatively wide.
2. It does **NOT** gate or enable any trade/execution. `confidence.gate_enabled_in_production: false`
   stays in force; the decision engine path is unchanged and frozen.
3. Required report fences whenever the stopgap IC is shown: a banner that says "diagnostic IC,
   over-covers ~0.86-0.91, NOT calibrated, not for sizing", and the per-CP coverage numbers.
4. The exit condition: the stopgap is RETIRED when a method passes the REQ-AUD-5 het gate in >= 2/3
   splits (e.g. a future T-9-5/T-9-6 GO). Until then it is the only interval the project displays, and
   only as a monitor.
5. Cross-reference: T-9-5 (native integer conformal) is the active attempt to replace this with a real
   calibrated IC; if T-9-5 also KILLs, this stopgap becomes the standing diagnostic until a new
   hypothesis (e.g. NWP-spread per T-9-6 feasibility) is available.

## Scope

ALLOWED: `docs/decisions/calibration_stopgap_2026-05-31.md` (the final memo). Read-only references to
existing reports. FORBIDDEN: any code change, any execution/Polymarket touch, any config flip (the memo
only DOCUMENTS that the existing `gate_enabled_in_production: false` stays). Doc-only.
