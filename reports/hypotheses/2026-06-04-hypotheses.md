# Hypothesis Catalog
Generated: 2026-06-04

- **H1** [pending]: Slope 3h (ΔT/hour) improves remaining_warming forecast (source: Reestruturação Achado 13)
- **H2** [pending]: Expected peak hour (by month×regime) improves MAE at CP (source: Reestruturação Achado 13)
- **H3** [pending]: Regime (calm/transition/late-warming) separates error significantly (source: model_error_taxonomy.md)
- **H4** [pending]: Dewpoint depression at CP carries signal for Tmax (source: Wilson & Fovell 2018)
- **H5** [pending]: T(D−1) adds predictive value beyond dminus1 pure (source: Auditoria #19)
- **H6** [pending]: Tmin of the day influences delta Tmax by regime×month (source: Auditoria #20)
- **H7** [pending]: Intraday regime transitions cause systematic error (source: Auditoria #14)
- **H8** [pending]: Wind direction change S→N precedes late-warming (source: EDA projeto, foehn literature)
- **H9** [pending]: Day sequences (A→B→C) have predictive structure (source: Auditoria #16)
- **H10** [pending]: Rain/clearing/post-frontal recovery cause regime errors (source: Auditoria #11, #15)
- **H11** [pending]: Tmax hour varies significantly by month×regime (P2) (source: Auditoria #12, #22)
- **H12** [pending]: Cloud cover reduces Tmax vs month×regime expectation (source: Auditoria #15)
- **H13** [pending]: Pressure trend (3h) signals regime change (source: Foehn literature, Reestruturação)
- **H14** [pending]: Composite foehn_score (NW-sector flow strength × dewpoint depression) segments error better than a direction-only or hard wind-speed cut (source: Regime classifier review 2026-06-04; eda_regime_path.py:262)
- **H15** [pending]: Late-warming measured as ΔT anomaly vs the hour's train-only climatology ('surprise') beats absolute Tmax-hour timing for segmenting late-warming error (source: Regime classifier review 2026-06-04; late_warming_bias_audit.md)
- **H16** [pending]: A continuous score-based regime classifier (argmax over foehn/late/calm/transition scores) generalizes better across seasons / ENSO phases than fixed boolean thresholds (source: Regime classifier review 2026-06-04)