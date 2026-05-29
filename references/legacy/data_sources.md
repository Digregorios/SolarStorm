# Data sources

## NZWN historic METAR (NZWN.csv)

- Source: Iowa Environmental Mesonet (IEM) ASOS network archive.
- URL pattern: https://mesonet.agron.iastate.edu/request/download.phtml?network=NZ__ASOS
- Station: NZWN (Wellington International Airport, New Zealand).
- Timezone of `valid` column: UTC (tz-naive in the CSV; treated as UTC by the ingest layer).
- Cadence: nominal 30 minutes; SPECI messages may appear off-cadence.
- Range observed in the local snapshot: 2020-01-01 to 2026-05-27 (~112,190 rows).
- Use: historic only. Live ingest must come from a feed contract registered in `contracts/resolver.md`.

## Citation

Iowa Environmental Mesonet, Iowa State University. ASOS-AWOS-METAR Network. Retrieved 2026.

## License / terms

The IEM ASOS download portal states the data are public domain (NOAA / FAA upstream). Uses must:
- preserve attribution to IEM,
- avoid mass mirroring without contacting IEM first,
- prefer derived/aggregated artefacts in this repo over the raw CSV (which is git-ignored).

## NWP forecasts (Phase 4+)

- Provider: Open-Meteo (https://open-meteo.com).
- Endpoints used: `historical-forecast-api.open-meteo.com` (continuous stitched
  timeseries) and `single-runs-api.open-meteo.com` (single-init causal lookup).
- Models in v1: ECMWF IFS HRES (9 km) and NCEP GFS (~13 km), per
  `contracts/nwp_source.md` v1.0.
- Upstream providers: ECMWF (European Centre for Medium-Range Weather Forecasts),
  NOAA NCEP (National Centers for Environmental Prediction).
- License: CC BY 4.0 (Creative Commons Attribution 4.0 International).
- Attribution requirement: any redistribution or derived publication MUST credit
  Open-Meteo and the upstream operational centers (ECMWF, NOAA NCEP).
- Tier: free non-commercial during research / Phase 4 backfill (10k calls/day,
  300k/month). Move to API Professional plan if live commercial use is required.
