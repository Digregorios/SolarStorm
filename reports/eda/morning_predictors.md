# Morning Predictors EDA

N days (day_complete): 2333
Material late-warming prevalence (k_eod - k_cp >= 2): 0.377

## Overall Correlations (Spearman)

| Feature | vs tmax_int | vs material_lw |
|---------|-------------|----------------|
| tmin_so_far_06 | 0.7711 | -0.1296 |
| t_06 | 0.7685 | -0.1335 |
| t_08 | 0.8421 | -0.0999 |
| delta_00_06 | -0.0728 | -0.086 |
| delta_06_cp | 0.3537 | 0.1883 |
| morning_rate | 0.3537 | 0.1883 |
| overnight_recovery | -0.154 | 0.0159 |
| tmax_d1 | 0.809 | -0.0078 |
| tmin_d1 | 0.7009 | -0.0834 |

## Binned Lift for material_lw

| Feature | base_rate | rate_Q1 | rate_Q4 | lift_Q4 |
|---------|-----------|---------|---------|---------|
| tmin_so_far_06 | 0.3772 | 0.485 | 0.3607 | 0.956 |
| t_06 | 0.3772 | 0.4737 | 0.3586 | 0.951 |
| t_08 | 0.3772 | 0.4692 | 0.364 | 0.965 |
| delta_00_06 | 0.3772 | 0.4065 | 0.3477 | 0.922 |
| delta_06_cp | 0.3772 | 0.2842 | 0.5025 | 1.332 |
| morning_rate | 0.3772 | 0.2842 | 0.5025 | 1.332 |
| overnight_recovery | 0.3772 | 0.3699 | 0.3897 | 1.033 |
| tmax_d1 | 0.3769 | 0.3921 | 0.4013 | 1.065 |
| tmin_d1 | 0.3769 | 0.4656 | 0.3574 | 0.948 |

## Seasonal Correlations (Spearman vs tmax_int)

| Feature | DJF | MAM | JJA | SON |
|---------|-----|-----|-----|-----|
| tmin_so_far_06 | 0.5192 | 0.6419 | 0.4625 | 0.6525 |
| t_06 | 0.5272 | 0.6425 | 0.5321 | 0.6607 |
| t_08 | 0.672 | 0.703 | 0.5667 | 0.7824 |
| delta_00_06 | 0.0332 | -0.0366 | 0.1398 | 0.0765 |
| delta_06_cp | 0.4718 | 0.2831 | 0.15 | 0.2958 |
| morning_rate | 0.4718 | 0.2831 | 0.15 | 0.2958 |
| overnight_recovery | 0.0123 | -0.0947 | 0.1215 | -0.022 |
| tmax_d1 | 0.4834 | 0.6589 | 0.5471 | 0.642 |
| tmin_d1 | 0.2799 | 0.5119 | 0.3022 | 0.5051 |

## Seasonal Correlations (Spearman vs material_lw)

| Feature | DJF | MAM | JJA | SON |
|---------|-----|-----|-----|-----|
| tmin_so_far_06 | -0.0554 | -0.2403 | -0.4186 | -0.2008 |
| t_06 | -0.0531 | -0.243 | -0.4155 | -0.1973 |
| t_08 | -0.0473 | -0.2144 | -0.3982 | -0.1418 |
| delta_00_06 | 0.0132 | -0.0938 | -0.1261 | -0.1053 |
| delta_06_cp | -0.031 | 0.2703 | 0.3562 | 0.1282 |
| morning_rate | -0.031 | 0.2703 | 0.3562 | 0.1282 |
| overnight_recovery | 0.0026 | 0.0093 | 0.0476 | 0.0387 |
| tmax_d1 | -0.0088 | -0.0748 | -0.1058 | -0.1008 |
| tmin_d1 | -0.0969 | -0.1637 | -0.2956 | -0.1491 |

## Key Findings

### Does T_06 predict Tmax?

Yes. Spearman(t_06, tmax_int) = 0.7685. The early-morning temperature
is a strong level predictor of the day's peak -- largely because both
track the seasonal cycle. Within-season correlations confirm residual
predictive power beyond pure seasonality.

### Does delta-from-min predict late spike?

Spearman(delta_06_cp, material_lw) = 0.1883.
Lift Q4 vs base: 1.332.
Surprisingly, days with LARGE morning warming (high delta_06_to_cp) are
MORE likely to continue warming after CP. This is moderate signal
(especially in JJA: rho=0.36, MAM: 0.27). The physical interpretation:
high-energy days (strong insolation, warm advection) warm both before
AND after CP. Cold-start days that stay flat in the morning tend to
stay flat afterward too. delta_06_cp is a useful positive predictor
of material late warming, particularly outside summer.

### Do cold-start-fast-warming days have higher upside?

Spearman(morning_rate, material_lw) = 0.1883.
Lift Q4 vs base: 1.332 (Q1 rate: 0.28, Q4 rate: 0.50).
Contrary to the "cold start = more room" hypothesis, fast morning
warming predicts MORE late warming, not less. Days with high energy
input warm throughout. The cold-start-high-upside theory is REJECTED
by this data. The actionable signal: if morning warming is strong,
expect continued warming after CP.

### Does tmax_d_minus_1 add beyond seasonality?

Spearman(tmax_d1, tmax_int) = 0.809.
Previous-day Tmax is a strong predictor of today's Tmax (persistence).
Within-season correlations show it retains value beyond the seasonal
cycle, confirming synoptic persistence as a real signal.
For material_lw: Spearman = -0.0078 -- weak, as expected (persistence
predicts level, not residual late warming).
