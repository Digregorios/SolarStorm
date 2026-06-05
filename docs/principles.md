# SolarStorm Design Principles (P1-P5)

These five principles are extracted from the codebase and govern every design decision. They are ranked by priority: P1 is the hardest constraint and failures cascade downward.

## P1: Causal Firewall

> **No future information leaks into any forecast.**

- Every feature at a checkpoint `cp_utc` must satisfy `feature_max_ts < cp_utc` (strict inequality). The observation timestamp of the latest input must be strictly before the checkpoint.
- Violation raises `RuntimeError` -- no silent fallback, no diagnostic downgrade.
- Internal computation uses **decimal** temperatures (`tmax_dec` from `tmpf`); the integer bracket is derived only at the output layer.
- Source: `solarstorm/_contracts.py` (`require_causal()`), `solarstorm/data/_labels.py` (`risco_de_flip()`).

**Why it is P1:** A forecast is worthless if it peeks at the answer. No other gate matters if causality is broken.

## P2: Evidence Over Parameters

> **No hardcoded meteorological constants except contractual CP_SET.**

- All thresholds, regimes, and climatological parameters must be data-driven, computed from the training set only.
- The sole exception: `CP_SET_UTC` (checkpoint hours) and `ICAO`/`TZ_NAME` are contractual constants defined in `_config.py`.
- Regime thresholds (`foehn_score > 60.0`, `max_delta > 1.0`, etc.) are calibrated on NZWN EDA, not baked in from the old project's fitted coefficients.
- Old Reports' fitted constants (e.g., "Tmax = T09 * 1.15 + 4") are deliberately excluded -- their backtests showed 33-38% out-of-sample vs inflated in-sample.

**Why it is P2:** The old Wellington project died from overfitted constants. If it cannot be derived from data, it does not go in.

## P3: Hypotheses Must Be Testable

> **Every EDA finding is registered as a gated hypothesis with bootstrap CI + FDR.**

- Each hypothesis gets a unique H-ID, a feature column, and a physical justification (source field).
- Validation is via the walk-forward harness: expanding-window splits, paired bootstrap CI (n=1000), Benjamini-Hochberg FDR correction at alpha=0.05.
- A hypothesis passes only if CI95 excludes zero, FDR survives, AND all five gates (G1-G5) pass.
- Failed hypotheses are documented with the same rigor as passed ones (P5).
- H17-H23 were mined from the old overfitted protocols but registered as gated tests -- they must earn their place, not inherit it.

**Why it is P3:** If you cannot test it, you cannot trust it. The old project's 50 theses were never falsified -- they were baked in.

## P4: Settlement Honesty

> **Decimal internally, integer output. Commercial rounding (half-up).**

- `integer_settlement(dec)` uses commercial rounding: `floor(dec + 0.5)`. 14.5 rounds to 15; -2.5 rounds to -2.
- `risco_de_flip` quantifies how close a decimal value is to a 0.5 degree boundary where 0.1 degree flips the Polymarket bracket.
  - 0.0 = exactly on a .5 boundary (no risk -- always rounds the same way).
  - 0.5 = exactly at an integer (max risk -- 0.1 degree changes the bracket).
- Source: `solarstorm/data/_settlement.py` (`FlipRisk`, `flip_risk()`).

**Why it is P4:** Polymarket contracts settle on integer degrees. How close we are to the boundary determines whether the forecast has practical edge or is noise.

## P5: Versioned Artifacts

> **All outputs timestamped, reproducible, JSON+MD format.**

- Every CLI command that produces output writes a versioned artifact to `reports/` (e.g., `reports/2026-06-05/hypothesis_results.json`).
- Stdout is an echo, not the authoritative record. The artifact is the truth.
- Leaderboard is a **permanent scoreboard** -- each run appends a dated entry, never overwrites.
- Reproducibility is anchored by `SEED = 42` in `_config.py`.
- Formats: JSON for machine consumption, Markdown for human review.

**Why it is P5:** The old project's results were scattered across notebooks and Slack threads. Versioned artifacts make the evaluation trail auditable and the leaderboard a living document.

## Cascade

These principles cascade: if P1 (causality) is violated, P3 (hypothesis testing) is meaningless. If P2 (evidence) is violated, P4 (settlement honesty) becomes a lie about precision. P5 (versioning) makes all others auditable.

## Source

Extracted from the codebase on 2026-06-04. These principles are **descriptive** -- they document what the code enforces, not what we wish it enforced.
