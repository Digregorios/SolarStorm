# Polymarket Tmax Forecaster (NZWN)

Intraday forecaster for Wellington (NZWN) integer Tmax in degC, with CP-aware
causality, calibrated confidence, late spike alert, and forensic anti-nowcaster
audit. Designed to feed Polymarket Tmax markets.

## Spec

The full spec lives under `.kiro/specs/polymarket-tmax-forecaster/`:

- [requirements.md](.kiro/specs/polymarket-tmax-forecaster/requirements.md)
- [design.md](.kiro/specs/polymarket-tmax-forecaster/design.md)
- [implementation-plan.md](.kiro/specs/polymarket-tmax-forecaster/implementation-plan.md)
- [tasks.md](.kiro/specs/polymarket-tmax-forecaster/tasks.md)
- [README.md](.kiro/specs/polymarket-tmax-forecaster/README.md)

## Status

| Phase | Status | Notes |
|---|---|---|
| 0 - Setup + contracts | DONE | Q_VERSION=1.0, FEATURES_VERSION=0.1, NWP_SOURCE_VERSION=1.0 |
| 1 - Data contracts + labels + EDA | DONE | 99.7% day_complete, 0% fallback, 0% decimal vs int discrepancy |
| 2 - Baselines + audit harness | DONE | persistence@cp23 28% > climatology 16%; H0 verdict file emitted |
| 3 - Ridge band-aware | DONE | REQ-MET-4 PASS 3/3; corr_diff gate FAIL (Phase 4 remediation) |
| 4 - NWP residual | BLOCKED | OPN-5 closed (Open-Meteo HFAPI + Single Runs). T-OPN-5a cross-check pending. |

## How to run (Windows-friendly)

```powershell
py -3 -m pip install -e .
py -3 scripts\smoke_phase1_2.py
py -3 scripts\eda_phase1.py
py -3 scripts\phase3_evaluate.py

py -3 -m core.cli.app forecast --csv NZWN.csv --date 2025-07-15 --cp 23
py -3 -m core.cli.app postmortem --csv NZWN.csv --date 2025-07-15 --forecast artifacts/forecasts/<run_id>.json
py -3 -m audits.run_h0_audit --train-end 2024-12-31 --test-end 2025-06-30

py -3 -m pytest -q
py -3 tools\reverse_import_guard.py .
py -3 tools\ascii_guard.py .
```

## Versions frozen

- `Q_VERSION = 1.0` - quantization (`contracts/quantization.md`)
- `IMPUTATION_VERSION = 1.0` - parser fallback policy
- `FEATURES_VERSION = 0.1` - 13 baseline features for Phase 3
- `OBJECTIVE_VERSION = 1.0` - `max EV s.t. drawdown<=5%`
- `NWP_SOURCE_VERSION = 1.0` - Open-Meteo + ECMWF IFS HRES + NCEP GFS

## Data

- `NZWN.csv` - IEM ASOS METAR (2020-01-01 to 2026-05-27, 30-min cadence). Excluded from git.
- See `references/legacy/data_sources.md` for attribution (IEM ASOS, Open-Meteo, ECMWF, NOAA NCEP - CC BY 4.0).
