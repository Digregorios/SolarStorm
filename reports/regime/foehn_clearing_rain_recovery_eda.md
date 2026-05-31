# Foehn / Clearing / Rain-Recovery EDA

N days: 2333
Base rate P(k_eod - k_cp >= 2): 0.3772
Base E[delta_k]: 1.337
Base P(tmax_hour > cp_hour): 0.5898

## Individual Proxy Cuts

| proxy | value | n | P(mlw) | lift | E[delta_k] | P(tmax_after) |
|---|---|---|---|---|---|---|
| wind_quadrant_change | E->W | 1 | 1.0 | 2.65 | 2.0 | 1.0 |
| wind_quadrant_change | S->N | 103 | 0.6408 | 1.7 | 1.854 | 0.7573 |
| wind_quadrant_change | E->S | 33 | 0.5455 | 1.45 | 2.0 | 0.8788 |
| wind_quadrant_change | E->E | 8 | 0.5 | 1.33 | 1.25 | 0.625 |
| wind_quadrant_change | W->N | 4 | 0.5 | 1.33 | 2.0 | 1.0 |
| wind_quadrant_change | W->S | 2 | 0.5 | 1.33 | 3.0 | 1.0 |
| foehn_like | True | 913 | 0.437 | 1.16 | 1.445 | 0.6243 |
| wind_quadrant_cp | N | 1433 | 0.4327 | 1.15 | 1.446 | 0.6267 |
| wind_quadrant_change | S->E | 14 | 0.4286 | 1.14 | 1.286 | 0.7143 |
| wind_quadrant_cp | E | 26 | 0.4231 | 1.12 | 1.231 | 0.6154 |
| wind_quadrant_change | N->N | 1313 | 0.4166 | 1.1 | 1.412 | 0.6146 |
| rain_stopped | False | 1797 | 0.4023 | 1.07 | 1.398 | 0.6077 |
| wind_quadrant_change | E->N | 13 | 0.3846 | 1.02 | 1.462 | 0.6923 |
| clearing_proxy | False | 2249 | 0.3797 | 1.01 | 1.344 | 0.5927 |
| foehn_like | False | 1420 | 0.3387 | 0.9 | 1.268 | 0.5676 |
| wind_quadrant_change | N->S | 249 | 0.3173 | 0.84 | 1.205 | 0.4458 |
| clearing_proxy | True | 84 | 0.3095 | 0.82 | 1.155 | 0.5119 |
| rain_stopped | True | 536 | 0.2929 | 0.78 | 1.132 | 0.5299 |
| wind_quadrant_cp | S | 857 | 0.2859 | 0.76 | 1.168 | 0.5309 |
| wind_quadrant_change | S->S | 573 | 0.2565 | 0.68 | 1.098 | 0.5462 |
| wind_quadrant_change | N->E | 4 | 0.25 | 0.66 | 1.0 | 0.25 |
| wind_quadrant_cp | W | 17 | 0.2353 | 0.62 | 0.882 | 0.4118 |
| wind_quadrant_change | N->W | 10 | 0.2 | 0.53 | 0.6 | 0.2 |
| wind_quadrant_change | S->W | 5 | 0.2 | 0.53 | 1.2 | 0.6 |
| wind_quadrant_change | W->W | 1 | 0.0 | 0.0 | 1.0 | 1.0 |

## Top Lift Proxies (vs base rate)

1. **wind_quadrant_change=E->W**: lift=2.65, P(mlw)=1.0, n=1
2. **wind_quadrant_change=S->N**: lift=1.7, P(mlw)=0.6408, n=103
3. **wind_quadrant_change=E->S**: lift=1.45, P(mlw)=0.5455, n=33
4. **wind_quadrant_change=E->E**: lift=1.33, P(mlw)=0.5, n=8
5. **wind_quadrant_change=W->N**: lift=1.33, P(mlw)=0.5, n=4
6. **wind_quadrant_change=W->S**: lift=1.33, P(mlw)=0.5, n=2
7. **foehn_like=True**: lift=1.16, P(mlw)=0.437, n=913
8. **wind_quadrant_cp=N**: lift=1.15, P(mlw)=0.4327, n=1433
9. **wind_quadrant_change=S->E**: lift=1.14, P(mlw)=0.4286, n=14
10. **wind_quadrant_cp=E**: lift=1.12, P(mlw)=0.4231, n=26