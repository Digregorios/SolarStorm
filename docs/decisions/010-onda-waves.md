# ADR-010: Onda Wave Methodology

- **Date:** 2026-06-04
- **Status:** Accepted

## Context

SolarStorm is a clean-slate rewrite of a prior NZWN forecasting project that produced no predictive value (NULL_NOT_BEATEN, negative skill vs persistence). The rewrite must avoid the same failure mode: building complex models on an untested foundation.

The project needs a phased delivery model where each wave (onda) depends on and validates the previous wave. No wave may skip ahead -- a model trained on biased features is no better than a coin flip, regardless of architecture.

## Decision

**Sequential waves (ondas) where each builds on the validation of the previous.**

### Onda 0: Scaffold (complete: 2026-06-04)
- Repository structure, tooling, CI
- Frozen principles P1-P5
- Data pipeline: IEM ASOS ingest, METAR parsing, obs.parquet, labels.parquet
- Causal firewall (P1)
- No models, no predictions -- infrastructure only

### Onda 1: Baselines (complete: 2026-06-04)
- L0-L4 baseline ladder (persistence, dminus1, climatology, empirical conditional)
- Walk-forward harness with expanding-window splits
- Frozen gates G1-G5 (G4 hard, non-demotable)
- Regime classifier (5 regimes, data-driven thresholds)
- Hypothesis catalog H1-H23 with bootstrap CI framework
- CLI: ingest, baselines, leaderboard, eda
- Leaderboard artifact generation (P5)
- 102 passing tests

### Onda 2: Prove Value (active)
- Live shadow window: weekly readiness reports
- Feature validation: walk-forward bootstrap CI + FDR on H1-H23
- Missing inventory, fallback distributions, NWP endpoint summary
- Baseline+Feature Nulls in leaderboard
- **Gate:** At least one feature must beat the best null baseline with validated CI and pass all gates. If no feature passes G1-G5, Onda 3 is blocked.

### Onda 3: Models (planned)
- ML models: LightGBM, quantile regression, NWP integration
- Model ladder: model beats best baseline at each CP
- Hyperparameter tuning within causal firewall
- Ensemble blending
- **Gate:** Model must beat best feature-null on walk-forward holdout. No model without validated features.

### Descontinuado (Discontinued)
- Wave 4+ (trading execution, position sizing, live deployment) are defined out of scope for the current project phase but remain as future reference.

## Wave Gate Rules

Each Onda N must satisfy:
1. All gates from Onda N-1 still pass (no regression).
2. The Onda N deliverable beats the best deliverable from Onda N-1 on the walk-forward holdout.
3. No feature or model is promoted without validated CI excluding zero and all gates passing.

## Alternatives Considered

1. **Single epic build:** Build the full pipeline (data + features + models + trading) in one go. Rejected -- this is what the old project did, and it masked foundation bugs until there was no time to fix them.
2. **Model-first:** Start with models and backfill baselines later. Rejected -- without baselines, there is no null to beat. You cannot know if a model is good or lucky.
3. **Waterfall (rigid phases):** Each wave must be 100% complete before starting the next. Rejected -- cross-wave feedback (e.g., a failing gate in Onda 2 may reveal a baseline bug in Onda 1) should feed back immediately.

## Consequences

### Enabled
- Each wave validates its dependents: features are only as good as the baselines they beat; models are only as good as the features they use.
- Clear go/no-go decisions: Onda 2 must prove features add value before Onda 3 invests in modeling.
- The baseline ladder serves as a permanent performance floor -- no model can claim victory without beating L0-L4.

### Prevents
- Building models on unvalidated features (the old project's core mistake).
- Shipping without knowing whether the foundation works.
- Premature optimization of model architecture when feature engineering is the bottleneck.

## References

- `CHANGELOG.md` -- Wave completion entries
- `docs/live_shadow_runbook.md` -- Onda 2 live shadow window operational procedures
- `docs/phase5_next_steps_2026-06-03.md` -- Phase 5 planning
- `solarstorm/__init__.py` -- `__version__ = "0.1.0"` (Onda 0+1)
