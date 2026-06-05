# Replication Guide — Adapting SolarStorm for Another City

This guide documents what needs to change to adapt SolarStorm from NZWN
(Wellington Airport) to another ICAO station. It assumes the new station has
IEM ASOS coverage and the forecasting target is the same: intraday Tmax for
Polymarket daily-maximum-temperature markets.

## What Changes

### 1. Station Identity (`solarstorm/_config.py`)

```python
ICAO = "NZWN"                        # → new station ICAO code
TZ_NAME = "Pacific/Auckland"        # → IANA timezone for the station
CP_SET_UTC = ("20:00", "21:00", "22:00", "23:00")  # → contract checkpoints in UTC
TMP_C_INT_PLAUSIBILITY = (-10, 40)  # → climate-appropriate bounds
SEED = 42                           # unchanged (reproducibility)
```

### 2. Checkpoint Times (CP_SET_UTC)

CP times are **UTC hours**, not local. For NZWN, 20:00-23:00 UTC = 08:00-11:00
NZST (morning). These are the Polymarket contract resolution checkpoints.

### 3. Data Source (`solarstorm/data/_iem.py`)

The IEM ASOS API is called with `station=<ICAO>`. Verify the station exists in
the IEM network: https://mesonet.agron.iastate.edu/request/asos/1hour.py

### 4. Climate Parameters

Regime classifier thresholds in `solarstorm/eda/_regimes.py` are calibrated for
NZWN's maritime temperate climate. Recalibrate for a different climate:

| Parameter | NZWN Default | Recalibration Method |
|-----------|-------------|---------------------|
| `max_delta > 1.0` for transition | 1.0 °C/h | Historical Tmax hour distribution |
| `max_delta < -2.0` for disrupted | -2.0 °C/h | Precipitation-disrupted days |
| `tmax_hour >= 18` for late_warming | 18 local | Station latitude and season |
| NW sector (270°–45°) | Wellington-specific | Local wind climatology |

## What Does NOT Change

These are **invariant** across stations:

| Component | Why Invariant |
|-----------|---------------|
| Causal firewall (`_contracts.py`) | `ts_utc < cp_utc` is logical, not meteorological |
| Integer settlement (`_settlement.py`) | Polymarket contract standard |
| Frozen gates G1-G5 (`_gates.py`) | Statistical quality gates |
| Walk-forward design (`_walkforward.py`) | Evaluation methodology |
| Bootstrap CI (`_bootstrap.py`) | Statistical inference |
| Hypothesis framework (`_hypotheses.py`) | FDR + gated testing |
| Commercial rounding | `floor(dec + 0.5)` is mathematical |

## Data Requirements

- **Minimum 5 years** of historical METAR data from IEM ASOS
- **≥365 complete days** for climatology fitting
- **≥365 training days** before first walk-forward test split

## Step-by-Step Adaptation

1. Fork/clone SolarStorm
2. Update `solarstorm/_config.py` with new station constants
3. Run `python -m solarstorm ingest` to backfill METAR
4. Verify `data/labels.parquet` has ≥365 complete days
5. Run `python -m solarstorm leaderboard` to establish baselines
6. Recalibrate regime thresholds by analyzing local climatology
7. Run `python -m solarstorm features` and `python -m solarstorm validate`
8. Review reports for local performance
