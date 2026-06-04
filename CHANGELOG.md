# Changelog

## 2026-06-04 — Onda 0+1 complete
- METAR ingestion 2009-2026 (IEM ASOS, parquet cache)
- Labels: Tmax/CP, k_cp, remaining_warming, risco_de_flip, 24h scan
- Baselines L0-L4: persistence, dminus1, climatology DOY+CP×mês, empirical conditional
- Walk-forward harness: expanding splits, holdout windows 7/14/30d
- Frozen gates G1-G5 (G4 anti-nowcaster hard, non-demotable)
- Regime classifier: calm/transition/late_warming/foehn_nw/disrupted
- Hypothesis catalog H1-H16 with bootstrap CI framework
- CLI: ingest, baselines, leaderboard, eda
- Leaderboard artifact: JSON+MD auto-generated per run (P5)

## 2026-06-04 — Project bootstrap
- Repo scaffold, pyproject.toml, README, CHANGELOG
