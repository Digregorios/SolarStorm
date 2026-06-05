# SolarStorm

Intraday Tmax probabilistic forecaster for NZWN (Wellington Airport).
Targets Polymarket daily-maximum-temperature markets.

## Quick Start

```bash
pip install -e ".[dev]"
python -m solarstorm ingest       # backfill METAR from IEM (2009-present)
python -m solarstorm features     # build feature columns
python -m solarstorm leaderboard  # generate baseline leaderboard
python -m solarstorm validate     # validate hypotheses with walk-forward CI
```

## Documentation

- [Architecture](docs/architecture.md) -- pipeline, modules, data flow
- [Principles](docs/principles.md) -- P1-P5 design principles
- [Decisions](docs/decisions/) -- architecture decision records
- [Replication Guide](docs/replication.md) -- adapting for another city
- [Bug Register](docs/bug-register.md) -- known issues and fixes
- [Glossary](docs/glossary.md) -- terminology

## Legacy

The prior Wellington iteration is archived at `archive/wellington-legacy` (git tag).
See `quarentena/` for historical reports and postmortems.
