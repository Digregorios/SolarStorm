# Live Shadow Ops Runbook (Phase 5.1)

Operational guide for running and monitoring the shadow forecast system.

---

## Quick Start

### 1. Run Shadow Forecasts (Single Date)

```bash
python scripts/run_shadow_ops_v1.py --date 2025-06-03
```

Output: `artifacts/shadow_ops/forecasts/2025-06-03.jsonl` (4 lines for CP20-23)

### 2. Run Shadow Forecasts (Date Range)

```bash
python scripts/run_shadow_ops_v1.py --start 2025-06-01 --end 2025-06-07
```

### 3. Force Re-run (Overwrite Existing)

```bash
python scripts/run_shadow_ops_v1.py --date 2025-06-03 --force
```

### 4. Generate Readiness Report

```bash
python scripts/live_shadow_readiness_report.py --shadow-root artifacts/shadow_ops
```

Output:
- `reports/live_shadow/readiness_v1.json`
- `reports/live_shadow/readiness_v1.md`

---

## Daily Operations

### Morning Checklist

1. **Verify yesterday's shadow run completed:**
   ```bash
   ls -la artifacts/shadow_ops/forecasts/$(date -d yesterday +%Y-%m-%d).jsonl
   ```

2. **Check for errors:**
   ```bash
   # Use the readiness report (not wc -l) to detect incompleteness.
   # Duplicates or unexpected CPs do NOT count as coverage.
   python scripts/live_shadow_readiness_report.py \
     --shadow-root artifacts/shadow_ops \
     --start $(date -d yesterday +%Y-%m-%d) \
     --end $(date -d yesterday +%Y-%m-%d)
   ```

3. **Run readiness report (weekly):**
   ```bash
   python scripts/live_shadow_readiness_report.py \
     --start $(date -d '30 days ago' +%Y-%m-%d) \
     --end $(date -d yesterday +%Y-%m-%d)
   ```

### Troubleshooting

| Symptom | Likely Cause | Action |
|---------|--------------|--------|
| File missing | Runner didn't execute | Run manually with `--force` |
| Readiness completeness < 1.0 | Missing CPs or unexpected CPs | Check NWP availability, re-run |
| `fallback_used: true` in records | NWP fetch failed | Check network, ECMWF/GFS status |
| Readiness gate FAIL | Incomplete data | Identify missing dates, re-run |

---

## Configuration

### Shadow Runner Options

| Option | Default | Description |
|--------|---------|-------------|
| `--shadow-root` | `artifacts/shadow_ops` | Output directory |
| `--cps` | `20,21,22,23` | Checkpoint hours (UTC) |
| `--force` | `false` | Overwrite existing files |
| `--timeout` | `120` | Subprocess timeout (seconds) |

### Readiness Report Options

| Option | Default | Description |
|--------|---------|-------------|
| `--shadow-root` | `artifacts/shadow_ops` | Input directory |
| `--start` | (none) | Start date filter |
| `--end` | (none) | End date filter |
| `--out-root` | `reports/live_shadow` | Output directory |
| `--git-sha` | `unknown` | Git SHA for report |

---

## Output Formats

### Forecast JSONL Schema

Each line in `forecasts/{date}.jsonl` contains:

```json
{
  "run_id": "uuid",
  "date_local": "2025-06-03",
  "cp_utc": "2025-06-03T20:00:00+00:00",
  "prob_dist": {"18": 0.3, "19": 0.5, "20": 0.2},
  "model_version": "phase3-ridge-band-v1.0",
  "routing": {
    "model_route": "ecmwf",
    "served_model": "ridge",
    "fallback_used": false,
    "fallback_reason": null,
    "ecmwf_cache_hit": true,
    "ecmwf_fetch_status": "success",
    "run_age_h": 6.5,
    "valid_time_delta_h": 12.0
  },
  "p50_int": 19,
  "ic80_low_int": 17,
  "ic80_high_int": 21
}
```

### Readiness Report Metrics

See `contracts/live_shadow_ops_v1_prereg.md` for metric definitions and gate thresholds.

---

## Scheduling (Recommended)

For automated daily execution via cron:

```cron
# Run shadow forecasts at 00:30 UTC daily (after NWP cycles available)
30 0 * * * cd /path/to/Wellington && python scripts/run_shadow_ops_v1.py --date $(date -d yesterday +%Y-%m-%d)

# Generate weekly readiness report (Monday 01:00 UTC)
0 1 * * 1 cd /path/to/Wellington && python scripts/live_shadow_readiness_report.py --start $(date -d '30 days ago' +%Y-%m-%d) --end $(date -d yesterday +%Y-%m-%d)
```

---

## Incident Response

If shadow system produces unexpected results:

1. **Stop shadow runner** (if scheduled)
2. **Document the issue** in postmortem
3. **Identify root cause** (NWP, cache, schema validation)
4. **Fix and re-run** affected dates with `--force`
5. **Re-generate readiness report** to verify fix

---

## Related Documents

- `contracts/live_shadow_ops_v1_prereg.md` - Promotion criteria
- `core/ops/shadow_runner.py` - Implementation
- `scripts/live_shadow_readiness_report.py` - Report generator
