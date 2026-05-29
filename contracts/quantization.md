# Contract: Quantization (Q_VERSION = 1.0)

> Source: REQ-CON-1. Frozen on 2026-05-29.

## Definitions

- Inverse band: `B(k) = [k - 0.5, k + 0.5)` for `k in Z`.
- Quantization function: `Q(x) = floor(x + 0.5)` (round-half-up).

## Properties

1. `Q(B(k)) == {k}` for any integer `k`.
2. `Q` partitions the real line into adjacent half-open intervals (no overlap, no gap).
3. The band is left-closed, right-open. A value exactly at the upper edge `k + 0.5` belongs to `B(k+1)`.

## Examples

| x        | Q(x) | Band             |
|----------|------|------------------|
| 18.49    | 18   | [17.5, 18.5)     |
| 18.50    | 19   | [18.5, 19.5)     |
| 18.99    | 19   | [18.5, 19.5)     |
| -0.5     | 0    | [-0.5, 0.5)      |
| -0.51    | -1   | [-1.5, -0.5)     |

## Where this is used

- Generating labels `tmax_int`, `tmin_int` (when applied to a continuous reading).
- Mapping `T_latent_dec` (model output) to `T_pred_int`.
- Computing distance-to-band for the band-aware loss.
- Cross-checking decimal vs integer in REQ-CON-3.

## Change protocol

Any change to `Q(x)` or `B(k)` requires:
1. bump of `Q_VERSION`,
2. bump of `criterion_version` in `audits/run_h0_audit.py`,
3. full re-run of the H0 audit,
4. comparative report in `reports/contract_change/q_<from>_to_<to>.md`.
