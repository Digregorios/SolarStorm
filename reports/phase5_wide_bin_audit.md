# Phase 5 - REQ-AUD-5 wide-bin audit (read-only)

Read-only diagnostic (update.txt Passo 1). NO method/gate/contract change. Method audited: standing **v1.0** normalized quantization-aware conformal (Track A.A1 and A.A3 both closed as real-but-insufficient). Normative intent + binning definition are frozen in `docs/req_aud5_normative.md`.

- Het band (unchanged): `[0.70, 0.90]`, 4 width bins (rank-based over distinct widths). Aggregate coverage target `0.80`.
- Binomial CI: Wilson score, 95% two-sided. A `coverage=1.000` with small `n` is a point estimate; read the Wilson interval.

## Per-bin coverage + Wilson 95% CI (v1.0, per split)

| split | bin | width [lo-hi] | n | succ | coverage | Wilson 95% CI | in band | gate match |
|-------|-----|---------------|---|------|----------|---------------|---------|------------|
| 2023-01-01_to_2023-12-31 | 0 | 1-5 | 1333 | 1094 | 0.821 | [0.799, 0.840] | True | True |
| 2023-01-01_to_2023-12-31 | 1 | 6-9 | 98 | 98 | 1.000 | [0.962, 1.000] | False | True |
| 2023-01-01_to_2023-12-31 | 2 | 10-13 | 18 | 18 | 1.000 | [0.824, 1.000] | False | True |
| 2023-01-01_to_2023-12-31 | 3 | 14-18 | 11 | 11 | 1.000 | [0.741, 1.000] | False | True |
| 2024-01-01_to_2024-12-30 | 0 | 1-5 | 1304 | 1132 | 0.868 | [0.849, 0.885] | True | True |
| 2024-01-01_to_2024-12-30 | 1 | 6-10 | 127 | 126 | 0.992 | [0.957, 0.999] | False | True |
| 2024-01-01_to_2024-12-30 | 2 | 11-15 | 18 | 18 | 1.000 | [0.824, 1.000] | False | True |
| 2024-01-01_to_2024-12-30 | 3 | 16-21 | 11 | 11 | 1.000 | [0.741, 1.000] | False | True |
| 2025-01-01_to_2025-12-31 | 0 | 1-3 | 1266 | 991 | 0.783 | [0.759, 0.805] | True | True |
| 2025-01-01_to_2025-12-31 | 1 | 4-6 | 161 | 159 | 0.988 | [0.956, 0.997] | False | True |
| 2025-01-01_to_2025-12-31 | 2 | 7-9 | 22 | 22 | 1.000 | [0.851, 1.000] | False | True |
| 2025-01-01_to_2025-12-31 | 3 | 10-12 | 11 | 11 | 1.000 | [0.741, 1.000] | False | True |

Reading: where the wide-bin Wilson interval still excludes the upper band edge (0.90), the over-coverage is unlikely to be pure sampling noise; where the interval straddles it, `n` is too small to call.

## Wide-bin composition (upper half of present bins, per split)

| split | wide bins | n rows | distinct dates | date range | by CP | sigma p50 | spread p50 |
|-------|-----------|--------|----------------|------------|-------|-----------|------------|
| 2023-01-01_to_2023-12-31 | [2, 3] | 29 | 21 | 2023-01-03..2023-12-19 | 22:00:9, 23:00:20 | 0.4564 | 0.000 |
| 2024-01-01_to_2024-12-30 | [2, 3] | 29 | 23 | 2024-01-01..2024-12-26 | 22:00:9, 23:00:20 | 0.3765 | 0.000 |
| 2025-01-01_to_2025-12-31 | [2, 3] | 33 | 22 | 2025-01-26..2025-12-22 | 22:00:11, 23:00:22 | 0.3821 | 0.000 |

### Wide-bin month histogram (operational-cluster check)

| split | by month (month:count) |
|-------|------------------------|
| 2023-01-01_to_2023-12-31 | 1:7, 2:3, 3:2, 5:2, 9:4, 10:6, 11:2, 12:3 |
| 2024-01-01_to_2024-12-30 | 1:8, 2:7, 3:6, 4:1, 9:1, 10:1, 11:1, 12:4 |
| 2025-01-01_to_2025-12-31 | 1:2, 2:8, 3:9, 4:4, 5:2, 6:2, 8:1, 11:4, 12:1 |

## Notes

- This artifact is read-only: no parameter, gate, window, or contract was changed.
- v1.0 is the standing method; A1/A3 are closed (real but insufficient).
- Decision on the next track (Track P: proxy/difficulty-axis change) is documented separately, docs-before-code, per update.txt Passo 2.
