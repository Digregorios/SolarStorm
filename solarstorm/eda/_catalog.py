"""Seed hypothesis catalog H1-H13 (P3). Each hypothesis becomes a gated EDA test.

Sources: Reestruturação_SolarStorm.txt, Wilson & Fovell 2018, model_error_taxonomy.md,
         auditoria forense items #8-#21, foehn literature.
"""
from __future__ import annotations

from solarstorm.eda._hypotheses import Hypothesis

SEED_HYPOTHESES: list[Hypothesis] = [
    Hypothesis(id="H1", feature_column="slope_3h",
               description="Slope 3h (ΔT/hour) improves remaining_warming forecast",
               source="Reestruturação Achado 13"),

    Hypothesis(id="H2", feature_column="hours_to_expected_peak",
               description="Expected peak hour (by month×regime) improves MAE at CP",
               source="Reestruturação Achado 13"),

    Hypothesis(id="H3", feature_column="regime_label",
               description="Regime (calm/transition/late-warming) separates error significantly",
               source="model_error_taxonomy.md"),

    Hypothesis(id="H4", feature_column="dewpoint_depression",
               description="Dewpoint depression at CP carries signal for Tmax",
               source="Wilson & Fovell 2018"),

    Hypothesis(id="H5", feature_column="tmax_dminus1",
               description="T(D−1) adds predictive value beyond dminus1 pure",
               source="Auditoria #19"),

    Hypothesis(id="H6", feature_column="tmin_delta_tmax",
               description="Tmin of the day influences delta Tmax by regime×month",
               source="Auditoria #20"),

    Hypothesis(id="H7", feature_column="intraday_regime_change",
               description="Intraday regime transitions cause systematic error",
               source="Auditoria #14"),

    Hypothesis(id="H8", feature_column="wind_dir_change_s_to_n",
               description="Wind direction change S→N precedes late-warming",
               source="EDA projeto, foehn literature"),

    Hypothesis(id="H9", feature_column="day_sequence_pattern",
               description="Day sequences (A→B→C) have predictive structure",
               source="Auditoria #16"),

    Hypothesis(id="H10", feature_column="precip_disruption",
               description="Rain/clearing/post-frontal recovery cause regime errors",
               source="Auditoria #11, #15"),

    Hypothesis(id="H11", feature_column="tmax_hour_by_regime_month",
               description="Tmax hour varies significantly by month×regime (P2)",
               source="Auditoria #12, #22"),

    Hypothesis(id="H12", feature_column="cloud_cover_suppression",
               description="Cloud cover reduces Tmax vs month×regime expectation",
               source="Auditoria #15"),

    Hypothesis(id="H13", feature_column="pressure_trend_3h",
               description="Pressure trend (3h) signals regime change",
               source="Foehn literature, Reestruturação"),

    # H14-H16: structural refinements to the regime classifier, registered here
    # as gated hypotheses rather than baked into the heuristic, so they earn
    # their place via walk-forward effect size + CI (P3) instead of being tuned
    # on a handful of unit fixtures.
    Hypothesis(id="H14", feature_column="foehn_score",
               description="Composite foehn_score (NW-sector flow strength × dewpoint "
                           "depression) segments error better than a direction-only or "
                           "hard wind-speed cut",
               source="Regime classifier review 2026-06-04; eda_regime_path.py:262"),

    Hypothesis(id="H15", feature_column="late_warming_anomaly",
               description="Late-warming measured as ΔT anomaly vs the hour's train-only "
                           "climatology ('surprise') beats absolute Tmax-hour timing for "
                           "segmenting late-warming error",
               source="Regime classifier review 2026-06-04; late_warming_bias_audit.md"),

    Hypothesis(id="H16", feature_column="regime_score_argmax",
               description="A continuous score-based regime classifier (argmax over "
                           "foehn/late/calm/transition scores) generalizes better across "
                           "seasons / ENSO phases than fixed boolean thresholds",
               source="Regime classifier review 2026-06-04"),
]
