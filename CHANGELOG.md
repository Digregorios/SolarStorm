# Changelog

**Onda** (Portuguese: "wave") is the phased development methodology used by SolarStorm.
Each onda depends on and validates the previous. See [ADR-010](docs/decisions/010-onda-waves.md).

---

## [v0.1.0] — 2026-06-05

### Documentation

- Created comprehensive documentation suite: architecture, principles, 10 ADRs,
  replication guide, bug register, glossary, feature contracts
- Rewrote README with documentation index and quick-start commands
- Organized CHANGELOG with version headers and Onda methodology definition

## [v0.1.0-alpha] — 2026-06-04

### Added (Bridge: CLI wiring + leaderboard feature nulls)

- CLI `features` command: loads obs/labels, calls `build_features`, writes `features.parquet` + coverage manifest
- CLI `validate` command: calls `validate_hypotheses`, exports hypothesis_results.json/md + validated_feature_contract.json
- Extended `leaderboard` command: L1 (dminus1) via self-join, L4 (empirical conditional) via `predict_dist` mode, baseline+feature null rows from validated contract via OLS challenger
- `export_leaderboard` now supports `feature_nulls` section in board dict + UTF-8 encoding on all `write_text` calls

### Added (Onda 0+1 complete)

- METAR ingestion 2009-2026 (IEM ASOS, parquet cache)
- Labels: Tmax/CP, k_cp, remaining_warming, risco_de_flip, 24h scan
- Baselines L0-L4: persistence, dminus1, climatology DOY+CPxmes, empirical conditional
- Walk-forward harness: expanding splits, holdout windows 7/14/30d
- Frozen gates G1-G5 (G4 anti-nowcaster hard, non-demotable)
- Regime classifier: calm/transition/late_warming/foehn_nw/disrupted
- Hypothesis catalog H1-H23 with bootstrap CI framework (H17-H23 mined from prior overfitted protocols -- registered as gated tests, not baked in)
- CLI: ingest, baselines, leaderboard, eda
- Leaderboard artifact: JSON+MD auto-generated per run (P5)

### Added (Project bootstrap)

- Repo scaffold, pyproject.toml, README, CHANGELOG
- 102 passing tests
