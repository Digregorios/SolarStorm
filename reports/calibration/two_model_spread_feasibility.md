# T-11-6: Two-Model Spread Feasibility

**Verdict: FEASIBLE-CONDITIONAL**

- Prereg: `contracts/two_model_spread_feasibility_v0_prereg.md` (v1.0)
- Window: 2024-03-01 to 2025-12-31 (ECMWF overlap, shorter than 2023-2025)
- Splits: 2 expanding folds within overlap window
- Best spread candidate: spread_at_cp (|GFS_t2m - ECMWF_t2m| at CP)
- Seed: 42, deterministic

## Gate Results

| Gate | Criterion | Result |
|------|-----------|--------|
| 1 | Spearman positive >= 2 folds | True (2/2) |
| 2 | Q4 > Q1 mean abs_error >= 2 folds | True (2/2) |
| 3 | Holds per CP esp CP20-22 | True |
| 4 | Causal + same rows + train-only | True |

## Per-CP Spearman(spread, abs_error)

| CP | Fold 1 | Fold 2 |
|----|--------|--------|
| 20:00 | 0.1185 | -0.0850 |
| 21:00 | 0.0639 | -0.0790 |
| 22:00 | 0.1198 | 0.0224 |
| 23:00 | 0.0482 | 0.1088 |

## Quartile Curve (mean abs_error by spread quartile)

### fold1

| CP | Q1 | Q2 | Q3 | Q4 | n |
|----|----|----|----|----|---|
| 20:00 | 1.000 | 0.907 | 0.733 | 1.375 | 178 |
| 21:00 | 0.885 | 0.935 | 0.765 | 1.130 | 178 |
| 22:00 | 0.778 | 0.609 | 0.844 | 0.881 | 178 |
| 23:00 | 0.695 | 0.541 | 0.775 | 0.667 | 178 |

### fold2

| CP | Q1 | Q2 | Q3 | Q4 | n |
|----|----|----|----|----|---|
| 20:00 | 1.000 | 0.719 | 0.630 | 0.804 | 184 |
| 21:00 | 0.927 | 0.853 | 0.791 | 0.742 | 184 |
| 22:00 | 0.738 | 0.875 | 0.568 | 0.758 | 184 |
| 23:00 | 0.643 | 0.583 | 0.639 | 0.763 | 184 |

## Strata Breakdown (non_calm / high_delta_06)

### fold1

| CP | Stratum | n | Spearman | Q1 | Q4 |
|----|---------|---|----------|----|----|
| 20:00 | non_calm | 105 | 0.1476 | 1.065 | 1.447 |
| 20:00 | high_delta_06 | 115 | 0.1859 | 1.029 | 1.425 |
| 21:00 | non_calm | 105 | 0.1631 | 0.913 | 1.314 |
| 21:00 | high_delta_06 | 115 | 0.0779 | 1.000 | 1.250 |
| 22:00 | non_calm | 105 | 0.1778 | 0.682 | 0.903 |
| 22:00 | high_delta_06 | 115 | 0.0858 | 0.935 | 0.879 |
| 23:00 | non_calm | 105 | 0.0730 | 0.679 | 0.690 |
| 23:00 | high_delta_06 | 115 | 0.1154 | 0.667 | 0.667 |

### fold2

| CP | Stratum | n | Spearman | Q1 | Q4 |
|----|---------|---|----------|----|----|
| 20:00 | non_calm | 126 | -0.1441 | 0.973 | 0.692 |
| 20:00 | high_delta_06 | 121 | -0.1634 | 0.971 | 0.692 |
| 21:00 | non_calm | 126 | -0.2184 | 0.967 | 0.600 |
| 21:00 | high_delta_06 | 121 | -0.1880 | 0.931 | 0.600 |
| 22:00 | non_calm | 126 | -0.0672 | 0.808 | 0.673 |
| 22:00 | high_delta_06 | 121 | -0.0726 | 0.800 | 0.652 |
| 23:00 | non_calm | 126 | 0.0006 | 0.769 | 0.745 |
| 23:00 | high_delta_06 | 121 | 0.1081 | 0.500 | 0.750 |

## Notes

- Anti-leakage: causal NWP (run_time <= cp - 60min), train-only quartile edges,
  train-only c30/P50, ex-ante regime (predicted risk, never truth), same rows.
- Window is shorter than full 2023-2025 due to ECMWF archive start (2024-03).
- Spread candidate: |GFS_t2m_at_cp - ECMWF_t2m_at_cp| per CP.
- Cross-fold sign consistency per CP: {'20:00': False, '21:00': False, '22:00': True, '23:00': True} (reversal=True).
- FEASIBLE-CONDITIONAL: gates met but the spread->error sign REVERSES by fold/season
  (CP20/CP21 flip). Usable ONLY as a season/regime-INTERACTED calibration difficulty
  axis (T-11-8 CQR), with mandatory ablation. NOT a standalone signal and NOT for
  point routing/serving. REQ-AUD-5 stays unchanged (no auto-reopen).
