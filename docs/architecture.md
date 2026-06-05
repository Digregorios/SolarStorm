# SolarStorm Architecture

Pipeline overview, module map, and data flow for the Onda 0+1 foundation.

## Pipeline

```
ingest → labels → features → baselines → validate → leaderboard
```

Each stage produces a versioned, reproducible artifact (P5). The pipeline is executed via the CLI (`tmax` entry point, defined in `solarstorm/__main__.py`).

## Data Flow

```
  IEM ASOS (HTTP)
       │
       ▼
  obs.parquet          ← ingest: fetch + parse METAR, persist enriched parquet
       │
       ▼
  labels.parquet       ← labels: Tmax/CP, k_cp, remaining_warming, day_complete
       │
       ▼
  features.parquet     ← features: causal feature columns (H1-H23) per (date, CP)
       │
       ▼
  hypothesis_results.json  ← validate: walk-forward bootstrap CI + FDR + gates
       │
       ▼
  leaderboard          ← leaderboard: permanent scoreboard artifact (JSON + MD)
```

## Module Map

```
solarstorm/
  __init__.py          # __version__ = "0.1.0"
  __main__.py          # CLI (typer): ingest, baselines, features, validate, leaderboard, eda
  _config.py           # Centralised constants: ICAO, TZ_NAME, CP_SET_UTC, SEED
  _contracts.py        # Causal firewall (P1): require_causal(), ensure_closed_left()
  data/
    _iem.py            # IEM ASOS HTTP client with parquet caching
    _metar.py          # Regex METAR parser (TT/DD from raw text)
    _obs.py            # Per-observation enrichment (dwp, dewpoint depression)
    _labels.py         # Daily Tmax labels, k_cp per CP, day_complete, risco_de_flip
    _calendar.py       # NZST/DST calendar: cp_to_utc(), day_local_window()
    _settlement.py     # Integer settlement: bracket_for(), flip_risk()
  baselines/
    _climatology.py    # L2: DOY-smoothed circular convolution (31d), monthly percentiles
    _empirical.py      # L4: Empirical conditional P(k_eod | month, CP, k_cp)
    _ladder.py         # Baseline ladder: LadderResult, best_null_for_cp()
    _persistence.py    # L0: Persistence baseline
  features/
    builder.py         # Causal feature builder: H1-H23 columns, coverage manifest
  eda/
    _catalog.py        # SEED_HYPOTHESES list (H1-H23)
    _hypotheses.py     # Hypothesis dataclass + run_hypothesis_test()
    _regimes.py        # 5-regime classifier: calm/transition/late_warming/foehn_nw/disrupted
    _validate.py       # Walk-forward bootstrap validation harness
  eval/
    _bootstrap.py      # Paired bootstrap CI for mean difference
    _gates.py          # Frozen gates G1-G5 (G4 non-demotable)
    _leaderboard.py    # Leaderboard builder + JSON/MD export
    _metrics.py        # Forecast evaluation metrics
    _segments.py       # Evaluation segments
    _walkforward.py    # Expanding-window walk-forward splits
```

## Key Contracts

| File              | Purpose                                                    |
|-------------------|------------------------------------------------------------|
| `_config.py`      | Station identity (ICAO=NZXN), CP set, timezone, seed      |
| `_contracts.py`   | Causal firewall invariant, temporal window semantics      |
| `_settlement.py`  | Integer output layer: commercial rounding, flip risk      |

## Directory Structure

```
data/                   # Parquet artifacts (obs, labels, features)
  obs.parquet
  labels.parquet
  features.parquet
reports/                # Versioned outputs (one subdir per date, P5)
  YYYY-MM-DD/
    hypothesis_results.json
    hypothesis_results.md
    validated_feature_contract.json
    feature_coverage.json
  leaderboard/
    YYYY-MM-DD-leaderboard.json
    YYYY-MM-DD-leaderboard.md
  hypotheses/
    YYYY-MM-DD-hypotheses.json
    YYYY-MM-DD-hypotheses.md
tests/                  # 102 unit tests
archive/wellington-legacy/  # Frozen prior iteration (no predictive value)
quarentena/             # Historical reports, postmortems, and legacy contracts
```

## Entry Points

```bash
pip install -e ".[dev]"
tmax ingest          # Backfill METAR from IEM (2009-present)
tmax features        # Build causal feature columns
tmax baselines       # Fit L0-L4 baselines
tmax leaderboard     # Evaluate baselines, export leaderboard
tmax validate        # Run hypothesis validation harness
tmax eda             # Export hypothesis catalog
```

## Design Principles Applied

- **P1 (Causal Firewall):** Every feature at a checkpoint uses only observations with `ts_utc < cp_utc`. Violation is a RuntimeError.
- **P4 (Settlement Honesty):** Decimal internally, integer output. Commercial rounding (half-up). `risco_de_flip` quantifies boundary risk.
- **P5 (Versioned Artifacts):** All outputs are timestamped, reproducible, in JSON+MD format.
