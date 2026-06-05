# ADR-003: Frozen Gates (G1-G5)

- **Date:** 2026-06-04
- **Status:** Accepted

## Context

The old Wellington project had a validation gate that flagged nowcast-suspect models. When a model failed, instead of fixing the issue, the team **demoted the gate to a diagnostic** -- the equivalent of removing a speed limit sign because too many drivers were speeding.

The line in the old project's `phase4_evaluate.py:95`:
```python
# G4: Corr_diff (nowcast discrimination) — demoted to diagnostic
```

This decision masked the fundamental problem (the model was a nowcaster in disguise) and allowed an overfitted model to proceed to production with inflated metrics.

The SolarStorm principle: gates are **frozen** once defined. A gate that fires is a finding, not a nuisance.

## Decision

Five frozen gates, applied to every hypothesis via `apply_all_gates()` in `solarstorm/eval/_gates.py`:

| Gate | Description                                   | Failure Status       | Condition                                    |
|------|-----------------------------------------------|----------------------|----------------------------------------------|
| G1   | Null not beaten                               | KILL                 | model_mae >= best_null_mae                   |
| G2   | Fallback dominance                            | NOT_OPERATIONAL      | fallback_rate > 0.50                         |
| G3   | p50 collapse                                  | COLLAPSE_ALERT       | p50_mode_share > 0.50                        |
| G4   | Anti-nowcaster (hard, non-demotable)          | NOWCAST_SUSPECT      | corr_diff < 0.05 or lo <= 0.0                |
| G5   | Best-null per CP                              | STAY_OUT             | per-CP model loses to best null              |

**G4 is non-demotable.** If `corr_diff` is unavailable (e.g., feature column not numeric), that is itself a G4 failure -- not a reason to skip the gate. This is the structural lesson from the old project.

All five gates must pass for a hypothesis to reach `validated` status in `validate_hypotheses()`.

## Alternatives Considered

1. **Soft gates (warnings):** Demote failing gates to diagnostics. Rejected -- this is exactly how the old project died.
2. **Gate weights:** Assign weights and compute a composite score. Rejected -- a KILL (G1) should never be offset by a passing G5. Gates are conjunctive, not compensatory.
3. **Threshold tuning post-results:** Adjust gate thresholds after seeing validation results. Rejected -- P2 (anti-gaming discipline). Gates are frozen before evaluation.

## Consequences

### Enabled
- Every hypothesis is judged against the same standard, forever.
- G4 forces explicit nowcast discrimination -- a model that improves on `k_cp` only because it is a better `k_cp` proxy fails.
- The old project's failure pattern (demote gate, ship overfitted model) is structurally impossible.

### Prevents
- Post-hoc relaxation of quality standards.
- "It's good enough for this CP" rationalization.
- Models that are closet nowcasters.

## References

- `solarstorm/eval/_gates.py` -- `apply_all_gates()`, `_g1_null_not_beaten()` through `_g5_per_cp()`
- `solarstorm/eda/_validate.py` -- `validate_hypotheses()`, status assignment at line 553-567
- Old project: `archive/wellington-legacy` (git tag), `quarentena/Wellington/` (postmortems)
