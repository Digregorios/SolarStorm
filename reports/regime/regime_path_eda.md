# Regime Path EDA

N days (day_complete): 2333
Base rate P(k_eod - k_cp >= 2): 0.3772
Base E[delta_k]: 1.337
Base P(tmax_hour > cp_hour): 0.5898

## Regime Path Cuts

| regime_path | n | P(mlw) | lift | E[delta_k] | P(tmax_after) |
|---|---|---|---|---|---|
| cloudy->dry->mild | 1 | 1.0 | 2.65 | 2.0 | 1.0 |
| dry->cloudy->mild | 1 | 1.0 | 2.65 | 2.0 | 0.0 |
| dry->rainy->cloudy | 1 | 1.0 | 2.65 | 3.0 | 1.0 |
| rainy->mild->cloudy | 10 | 0.8 | 2.12 | 2.2 | 0.8 |
| dry->mild->mild | 13 | 0.7692 | 2.04 | 1.769 | 0.9231 |
| dry->mild->dry | 21 | 0.7143 | 1.89 | 1.81 | 0.8571 |
| dry->mild->rainy | 5 | 0.6 | 1.59 | 1.2 | 0.6 |
| mild->mild->mild | 421 | 0.5606 | 1.49 | 1.841 | 0.6888 |
| dry->cloudy->cloudy | 9 | 0.5556 | 1.47 | 1.667 | 0.7778 |
| mild->cloudy->cloudy | 55 | 0.5273 | 1.4 | 1.527 | 0.6182 |
| mild->mild->cloudy | 65 | 0.5231 | 1.39 | 1.662 | 0.6769 |
| cloudy->mild->mild | 55 | 0.5091 | 1.35 | 1.782 | 0.6182 |
| dry->mild->cloudy | 6 | 0.5 | 1.33 | 1.5 | 0.8333 |
| rainy->mild->mild | 84 | 0.4405 | 1.17 | 1.476 | 0.619 |
| mild->rainy->cloudy | 7 | 0.4286 | 1.14 | 1.143 | 0.5714 |
| rainy->rainy->dry | 17 | 0.4118 | 1.09 | 1.353 | 0.5882 |
| mild->mild->dry | 337 | 0.4065 | 1.08 | 1.463 | 0.6499 |
| cloudy->cloudy->rainy | 5 | 0.4 | 1.06 | 1.2 | 0.4 |
| mild->cloudy->mild | 50 | 0.4 | 1.06 | 1.46 | 0.52 |
| mild->mild->rainy | 35 | 0.4 | 1.06 | 1.257 | 0.5714 |
| dry->dry->cloudy | 8 | 0.375 | 0.99 | 1.125 | 0.625 |
| cloudy->mild->cloudy | 27 | 0.3704 | 0.98 | 1.111 | 0.4815 |
| cloudy->cloudy->cloudy | 71 | 0.3662 | 0.97 | 1.479 | 0.662 |
| dry->rainy->rainy | 11 | 0.3636 | 0.96 | 0.909 | 0.3636 |
| rainy->dry->dry | 31 | 0.3548 | 0.94 | 1.29 | 0.6129 |
| cloudy->cloudy->dry | 26 | 0.3462 | 0.92 | 1.154 | 0.6538 |
| dry->cloudy->dry | 9 | 0.3333 | 0.88 | 1.111 | 0.5556 |
| dry->dry->mild | 6 | 0.3333 | 0.88 | 0.667 | 0.3333 |
| mild->rainy->dry | 9 | 0.3333 | 0.88 | 1.222 | 0.6667 |
| cloudy->mild->dry | 38 | 0.3158 | 0.84 | 1.184 | 0.5526 |
| rainy->cloudy->mild | 19 | 0.3158 | 0.84 | 1.421 | 0.5263 |
| cloudy->cloudy->mild | 35 | 0.3143 | 0.83 | 1.229 | 0.4571 |
| mild->cloudy->rainy | 10 | 0.3 | 0.8 | 1.4 | 0.7 |
| rainy->cloudy->cloudy | 30 | 0.3 | 0.8 | 1.133 | 0.5667 |
| dry->dry->dry | 106 | 0.2925 | 0.78 | 1.189 | 0.6132 |
| rainy->mild->dry | 52 | 0.2885 | 0.76 | 1.077 | 0.5577 |
| cloudy->dry->dry | 15 | 0.2667 | 0.71 | 1.067 | 0.4667 |
| mild->dry->dry | 70 | 0.2571 | 0.68 | 0.957 | 0.5429 |
| rainy->rainy->mild | 59 | 0.2542 | 0.67 | 1.068 | 0.5085 |
| cloudy->mild->rainy | 4 | 0.25 | 0.66 | 1.25 | 0.75 |
| cloudy->rainy->cloudy | 8 | 0.25 | 0.66 | 1.25 | 0.5 |
| dry->rainy->mild | 4 | 0.25 | 0.66 | 1.0 | 0.75 |
| rainy->dry->cloudy | 4 | 0.25 | 0.66 | 1.0 | 0.5 |
| mild->cloudy->dry | 29 | 0.2414 | 0.64 | 1.034 | 0.6207 |
| rainy->rainy->cloudy | 32 | 0.2188 | 0.58 | 1.031 | 0.5625 |
| mild->dry->cloudy | 5 | 0.2 | 0.53 | 1.4 | 0.6 |
| mild->dry->rainy | 5 | 0.2 | 0.53 | 0.8 | 0.6 |
| mild->rainy->rainy | 45 | 0.2 | 0.53 | 1.133 | 0.4444 |
| rainy->mild->rainy | 26 | 0.1923 | 0.51 | 0.769 | 0.3846 |
| rainy->rainy->rainy | 267 | 0.1835 | 0.49 | 0.76 | 0.4157 |
| cloudy->rainy->rainy | 17 | 0.1765 | 0.47 | 0.765 | 0.2941 |
| mild->rainy->mild | 14 | 0.1429 | 0.38 | 0.857 | 0.5714 |
| rainy->cloudy->rainy | 8 | 0.125 | 0.33 | 0.625 | 0.375 |
| dry->dry->rainy | 10 | 0.1 | 0.27 | 0.8 | 0.7 |
| cloudy->rainy->dry | 1 | 0.0 | 0.0 | 1.0 | 0.0 |
| cloudy->rainy->mild | 8 | 0.0 | 0.0 | 0.625 | 0.5 |
| dry->rainy->dry | 2 | 0.0 | 0.0 | 0.5 | 0.5 |
| mild->dry->mild | 4 | 0.0 | 0.0 | 0.5 | 0.5 |
| rainy->cloudy->dry | 4 | 0.0 | 0.0 | 0.75 | 0.25 |
| rainy->dry->mild | 1 | 0.0 | 0.0 | 1.0 | 1.0 |
| rainy->dry->rainy | 5 | 0.0 | 0.0 | 0.4 | 0.2 |

## Regime Path Transition Table (count)

| w1 \ w3 | cloudy | dry | mild | rainy |
|---|---|---|---|---|
| cloudy | 106 | 80 | 99 | 26 |
| dry | 24 | 138 | 24 | 26 |
| mild | 132 | 445 | 489 | 95 |
| rainy | 76 | 104 | 163 | 306 |