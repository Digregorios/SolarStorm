# Contract: Polymarket resolver (RESOLVER_VERSION = 0.1)

> Source: REQ-CON-2, OPN-1a (minimal validation only).
> Frozen on 2026-05-29 as v0.1 (Phase 1 enable).
> Will be promoted to v1.0 in Phase 8 after the 30+ day binary audit (T-8-1).

## Minimal validation (OPN-1a)

| Field            | Value                                                       |
|------------------|-------------------------------------------------------------|
| Station / ICAO   | `NZWN` (Wellington International Airport)                   |
| Timezone         | `Pacific/Auckland` (uses NZDT/NZST per ZoneInfo)            |
| Day window       | `00:00:00` to `23:59:59.999` local (24h, REQ-CON-4)         |
| Truth source     | integer degC from raw `metar` field (`T_obs_int`, REQ-CON-3) |
| Quantization     | `Q_VERSION = 1.0` (default; pending v1.0 binary audit)      |
| CP set           | `[20:00, 21:00, 22:00, 23:00] UTC` (REQ-CON-6)              |
| CP operacional   | `23:00 UTC` (~11:00 local)                                  |

## Pending for v1.0

- `feed_source`: which exact Polymarket-resolved feed is consumed (TBD; depends on T-8-1).
- `speci_handling`: SPECI messages between regular METARs - included by default; audited in T-8-1.
- `missing_metar_policy`: a missing regular METAR does NOT extend the window; the day stays open until 23:59:59.999 local.

## Polymarket event URL / slug pattern (DETERMINISTIC; live-only context)

Every city+date Tmax market uses the SAME slug pattern - no per-market config needed:

```
https://polymarket.com/event/highest-temperature-in-<city>-on-<month>-<day>-<year>
# e.g. highest-temperature-in-wellington-on-may-31-2026
```

- `<city>` slugified lowercase (spaces -> '-'); `<month>` full lowercase name; `<day>` no
  leading zero; `<year>` 4 digits. Derived in code by `core/ingest/odds.py::event_slug`.
- Live prices via the Gamma API: `gamma-api.polymarket.com/events?slug=<slug>`. The event holds
  one `market` per integer-degC bracket with `groupItemTitle` (e.g. "11C or below", "18C",
  "21C or higher"), `outcomes` ["Yes","No"] and `outcomePrices` [YES,NO].
- Bracket -> `ContractRange`: "N or below" => `k_hi=N`; bare "N" => `k_lo=k_hi=N`; "N or
  higher/above" => `k_lo=N`. Resolution source is Wunderground NZWN, whole degrees C.
- Odds are captured ONLY at the live forecast CP (REQ-DEC-4) for EV/Kelly context; there is no
  historical odds dataset and no backtest over odds.

## Change protocol

Promotion from v0.1 to v1.0 requires the audit report `reports/resolver_audit.md` and a successful T-8-1.
