# EDA intro - Phase 1 (T-1-8, REQ-MET-2, REQ-CON-7)

## 10 key numbers

1. n_obs (raw IEM rows): 112189
2. parser fallback_rate: 0.000000
3. n_days: 2340
4. n_day_complete: 2333 (0.9970)
5. tmax_int median (complete days): 17
6. tmax_int min: 8
7. tmax_int max: 29
8. tmax_hour_local median: 12.0
9. early_peak_rate (hour < 12): 0.3330
10. outlier_hour_rate (hour in [0,6) U [22,24)): 0.1269

## Tables

- `tmax_hour_local_by_month.csv` - p10..p90 of local Tmax hour per month
- `early_peak_by_month.csv` - rate of early peak / outlier hour per month
- `coverage_by_month.csv` - day_complete ratio per (year, month)
- `tmax_distribution_by_month.csv` - histogram (month, k, count)
