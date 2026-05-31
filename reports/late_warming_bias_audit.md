# Late-warming bias audit (walk-forward OOS, operational CP)

_Read-only. Signed error = truth_int - p50; mean_err>0 means the center is too COLD; cold_rate = share of days the center underpredicts. Per-split train-only climatology._

- n_rows (OOS test days): 1095

## Overall bias by center

| arm | n | mean_err | cold_rate | MAE |
|-----|---|----------|-----------|-----|
| ridge | 1095 | -0.018 | 0.243 | 0.678 |
| empirical | 1095 | -0.134 | 0.407 | 2.065 |
| climatology | 1095 | +0.079 | 0.452 | 1.780 |
| persistence | 1095 | +1.322 | 0.745 | 1.322 |

## Ridge bias on late-spike vs non-late-spike days (the key cut)

| subset | n | mean_err | cold_rate | MAE |
|--------|---|----------|-----------|-----|
| late_spike | 816 | +0.254 | 0.316 | 0.612 |
| no_late_spike | 279 | -0.814 | 0.029 | 0.871 |

## Ridge bias by late-warming magnitude (k_eod - k_cp; clipped [-2,4])

| mag | n | mean_err | cold_rate |
|-----|---|----------|-----------|
| 0 | 279 | -0.814 | 0.029 |
| 1 | 407 | -0.292 | 0.037 |
| 2 | 264 | +0.394 | 0.432 |
| 3 | 93 | +1.075 | 0.828 |
| 4 | 52 | +2.346 | 1.000 |

## All centers on late-spike days only

| arm | n | mean_err | cold_rate | MAE |
|-----|---|----------|-----------|-----|
| ridge | 816 | +0.254 | 0.316 | 0.612 |
| empirical | 816 | +0.203 | 0.453 | 2.020 |
| climatology | 816 | +0.407 | 0.511 | 1.784 |
| persistence | 816 | +1.775 | 1.000 | 1.775 |

## Verdict

- The Ridge is NOT structurally cold overall (mean_err -0.018, cold_rate 0.24); it is near-unbiased / slightly warm on the 63% of days with little post-CP warming (mag 0-1).
- The cold bias is REAL but NARROW and PROPORTIONAL to post-CP warming magnitude (k_eod - k_cp): +0.39 at mag 2, +1.08 at mag 3, +2.35 at mag 4+. The 4 fresh days were mag 2-4 cases - a genuine failure regime, NOT an adversarial fluke.
- It is a CAUSAL-HORIZON limit, not a Ridge-specific defect: on late-spike days EVERY center is cold (ridge +0.25, empirical +0.20, climatology +0.41, persistence +1.78). The afternoon-warming signal simply does not exist at the CP. The Ridge is in fact the best center on late-spike days (lowest MAE 0.61).
- Implication: the remaining edge is a late-spike-aware center adjustment (or routing to the Phase-7 spike signal), NOT a blind p50 refit. Do not over-correct the 37% warming days at the cost of the 63% calm days.
