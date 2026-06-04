# SolarStorm

Intraday Tmax probabilistic forecaster for NZWN (Wellington Airport).
Targets Polymarket daily-maximum-temperature markets.

## Quick Start

pip install -e ".[dev]"
python -m solarstorm ingest   # backfill METAR from IEM
python -m solarstorm leaderboard

## Design

See docs/specs/ for wave-level design documents.
