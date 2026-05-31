# Delta from Min Analysis

## Definitions

- daily_amplitude = tmax_int - tmin_int
- delta_min_to_cp = k_cp - tmin_so_far_06 (warming achieved by CP)
- remaining_after_cp = tmax_int - k_cp (upside after CP)

## Distributions

| Metric | mean | std | p10 | p25 | median | p75 | p90 |
|--------|------|-----|-----|-----|--------|-----|-----|
| daily_amplitude | 5.51 | 2.39 | 3.0 | 4.0 | 5.0 | 7.0 | 9.0 |
| delta_min_to_cp | 3.44 | 2.1 | 1.0 | 2.0 | 3.0 | 5.0 | 6.0 |
| remaining_after_cp | 1.34 | 1.18 | 0.0 | 0.0 | 1.0 | 2.0 | 3.0 |

## P(remaining >= 2) by delta_min_to_cp bin

- Overall: 0.3772
- Low (Q1, delta_min_to_cp <= 2.0): 0.2822
- Mid (Q2): 0.3671
- High (Q4): 0.5474

Spearman(delta_min_to_cp, remaining_after_cp) = 0.2019

## Interpretation

When delta_min_to_cp is LOW (the day has not warmed much by CP),
is there still upside? The conditional probability P(remaining>=2 | low)
= 0.2822 vs overall 0.3772.

The relationship is not as expected. Days with high morning warming
also tend to have high remaining potential, suggesting the amplitude
is driven by overall energy (high-amplitude days warm both early and late).

## By Season

| Season | n | Spearman(dmc,rem) | P(rem>=2) | mean_amplitude |
|--------|---|-------------------|-----------|----------------|
| DJF | 600 | 0.0129 | 0.4317 | 5.77 |
| MAM | 637 | 0.2573 | 0.4003 | 5.57 |
| JJA | 551 | 0.3429 | 0.3702 | 5.26 |
| SON | 545 | 0.1568 | 0.2972 | 5.39 |
