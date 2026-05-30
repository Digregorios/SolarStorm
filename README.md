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
| 3 - Ridge band-aware | DONE | REQ-MET-4 PASS 3/3; corr_diff gate FAIL (demoted to diagnostic in Phase 4) |
| 4 - NWP residual | DONE | GFS s3_grib max-trajectory anchor; paired-ablation pooled 3/3; phase4_ready=True |
| 5 - Calibration + confidence | CLOSED NOT READY | v1.0/A1/A3/P/P'/D1/S all failed REQ-AUD-5 het gate; IC80/confidence diagnostic-only, fenced from trading |
| 6 - AR online | PARTIAL | AR(7) corrector + state/backup/dedupe done; DM-test (T-6-3) deferred |
| 7 - Late spike | DONE | REQ-SPK-3 PASS 3/3 (PR-AUC ~0.95 vs prevalence ~0.82); spike_risk wired to confidence + decision |
| 8 - Decision + live odds | OFFLINE DONE | decide() + market_map + sizing (EV/Kelly) + live Polymarket odds snapshot + live METAR fetch; realized-EV is live-gated |

See `docs/PROJECT_JOURNEY.md` for the full path (attempts, failures, decisions) and
`reports/model_metrics_summary.md` for consolidated model metrics.

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
- `OBJECTIVE_VERSION = 1.0` - offline: `max bracket_match_when_traded s.t. coverage>=25%` (odds-free); EV/Kelly are live-only (odds are live context, not a dataset)
- `NWP_SOURCE_VERSION = 1.0` - Open-Meteo + ECMWF IFS HRES + NCEP GFS

## Data

- `NZWN.csv` - IEM ASOS METAR (2020-01-01 to 2026-05-27, 30-min cadence). Excluded from git.
- See `references/legacy/data_sources.md` for attribution (IEM ASOS, Open-Meteo, ECMWF, NOAA NCEP - CC BY 4.0).
