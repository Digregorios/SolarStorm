"""D1-D6 over-coverage diagnostic for the Phase-4 CQR KILL (read-only, no remedy).

The Phase-4 CQR object was KILLed for OVER-coverage at integer granularity
(global IC80 0.92/0.90/0.93). This script does NOT re-open the gate or choose a fix;
it produces an evidence-only F1/F2/F3 verdict so Onda 2 can branch:

  F1 = base quantile boosters over-fit (over-coverage rises with width)
  F2 = quantile crossing / clamp inflates the band
  F3 = CQR can only widen / integer-granularity floor (no conformal fix exists)

It re-fits the SAME frozen CQR config the eval used (imported from
``scripts.evaluate_cqr_lightgbm_quantile``) on the SAME fit/calib/test slices and
computes six diagnostics. D6 is an ORACLE lower-bound that peeks at test truth: it is
explicitly DIAGNOSTIC-ONLY and is never used as a model-selection signal (anti-gaming).

Determinism: seed 42 (inherited from the eval module's module-level np.random.seed),
lightgbm deterministic=True, num_threads=1. Run ONCE.

Scope: this file + reports/calibration/cqr_overcoverage_diagnostic.{json,md}. It imports
(does not modify) the frozen eval script and core/models/quantile_lgbm.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np

# Allow importing the sibling FROZEN eval module when run as a plain script
# (py -3 scripts/diagnose_cqr_overcoverage.py): scripts/ is not a package, so put
# the repo root on sys.path. Under pytest the rootdir is already importable.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.baselines.climatology import fit_climatology, fit_tmax_hour_climatology
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.gates_phase5 import heteroscedasticity_gate
from core.features.training_panel import build_training_panel
from core.ingest.iem_csv import load_observations
from core.ingest.nwp import read_snapshots
from core.ingest.nwp_client import ECMWF_IFS_HRES, NCEP_GFS
from core.labels.tmax import build_tmax_labels
from core.models.late_warming_risk import build_features as build_risk_features
from core.models.quantile_lgbm import (
    QuantileLgbmConfig,
    conformalize,
    fit_quantile_lgbm,
    predict_interval_int,
    predict_quantiles,
)

# Reuse the FROZEN eval's data setup, constants, and helpers (no copy-drift).
from scripts.evaluate_cqr_lightgbm_quantile import (
    CALIB_FRAC,
    COVERAGE,
    CPS,
    FULL_SPLITS,
    LATE_CP,
    N_ESTIMATORS,
    OBS_GFS_FEATURES,
    REPO,
    SEED,
    _CLIM_IDX,
    _arrays,
    _causal_climo,
    _clim_vec,
    _regime_masks,
)

# Het-gate band (REQ-AUD-5) -- explicit so the diagnostic is self-documenting.
from core.contracts.phase5 import (
    HETEROSCED_COVERAGE_HIGH,
    HETEROSCED_COVERAGE_LOW,
    HETEROSCED_N_BINS,
)

STRATA = ("ALL", "calm", "non_calm", "high_delta", "late_cp_23")


# --------------------------------------------------------------------------- #
# pure diagnostic helpers (unit-pinned in tests/unit/test_diagnose_cqr_overcoverage.py)
# --------------------------------------------------------------------------- #
def pinball_loss(q: np.ndarray, y: np.ndarray, alpha: float) -> float:
    """Mean pinball (quantile) loss of predictions ``q`` at level ``alpha`` vs ``y``."""
    q = np.asarray(q, dtype=float)
    y = np.asarray(y, dtype=float)
    if q.size == 0:
        return float("nan")
    diff = y - q
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1.0) * diff)))


def crossing_frequency(raw_q_lo: np.ndarray, raw_q_hi: np.ndarray) -> float:
    """Fraction of rows where the RAW (pre-repair) low booster exceeds the high one."""
    lo = np.asarray(raw_q_lo, dtype=float)
    hi = np.asarray(raw_q_hi, dtype=float)
    if lo.size == 0:
        return float("nan")
    return float(np.mean(lo > hi))


def oracle_min_width_80(y: np.ndarray, coverage: float = COVERAGE) -> int:
    """Smallest integer fixed-width window covering >= ``coverage`` of ``y`` (oracle).

    DIAGNOSTIC ONLY -- this peeks at the test truth to characterise the integer
    granularity floor. It is never used to select or tune a model.
    """
    yi = np.round(np.asarray(y, dtype=float)).astype(int)
    n = yi.size
    if n == 0:
        return 0
    lo_grid, hi_grid = int(yi.min()), int(yi.max())
    need = int(np.ceil(coverage * n))
    for w in range(0, hi_grid - lo_grid + 1):
        # width w means a window [s, s+w] spanning w+1 integer brackets.
        best = 0
        for s in range(lo_grid, hi_grid - w + 1):
            cnt = int(np.sum((yi >= s) & (yi <= s + w)))
            if cnt > best:
                best = cnt
            if best >= need:
                return w + 1  # report width in integer brackets (hi - lo + 1)
        if best >= need:
            return w + 1
    return hi_grid - lo_grid + 1


def width_attribution(base_lo, base_hi, cqr_lo, cqr_hi) -> dict:
    """Mean base-band vs post-CQR integer width and the fraction CQR contributes."""
    bl = np.round(np.asarray(base_lo, dtype=float)).astype(int)
    bh = np.round(np.asarray(base_hi, dtype=float)).astype(int)
    cl = np.asarray(cqr_lo, dtype=int)
    ch = np.asarray(cqr_hi, dtype=int)
    w_base = (bh - bl + 1).astype(float)
    w_cqr = (ch - cl + 1).astype(float)
    mean_base = float(np.mean(w_base)) if w_base.size else float("nan")
    mean_cqr = float(np.mean(w_cqr)) if w_cqr.size else float("nan")
    extra = mean_cqr - mean_base
    frac = (extra / mean_cqr) if mean_cqr else float("nan")
    return {
        "mean_base_width": round(mean_base, 4),
        "mean_cqr_width": round(mean_cqr, 4),
        "cqr_added_width": round(extra, 4),
        "cqr_width_fraction": round(frac, 4),
    }


def _raw_quantiles(model, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """RAW pre-repair booster outputs (no min/max sort) for the crossing diagnostic."""
    Xc = X.copy()
    inds = np.where(np.isnan(Xc))
    if inds[0].size:
        Xc[inds] = np.take(model.feature_means_for_imputation, inds[1])
    raw_lo = np.asarray(model.booster_lo.predict(Xc, num_iteration=model.best_iter_lo), dtype=float)
    raw_hi = np.asarray(model.booster_hi.predict(Xc, num_iteration=model.best_iter_hi), dtype=float)
    return raw_lo, raw_hi


def _coverage(lo, hi, y) -> float:
    lo = np.asarray(lo)
    hi = np.asarray(hi)
    y = np.asarray(y)
    if y.size == 0:
        return float("nan")
    return float(np.mean((lo <= y) & (y <= hi)))


# --------------------------------------------------------------------------- #
# per (split, CP): re-fit CQR and compute D1-D5 row arrays                     #
# --------------------------------------------------------------------------- #
def _diagnose_one_cp(panel, cp, tr_start, tr_end, te_start, te_end, climo, risk_df_full,
                     tau, mode, n_estimators):
    sub = panel.filter((panel["cp"] == cp) & panel["nwp_t2m_maxtraj_c"].is_not_null())
    import polars as pl

    tr = sub.filter((pl.col("date_local") >= tr_start) & (pl.col("date_local") <= tr_end)).sort("date_local")
    te = sub.filter((pl.col("date_local") >= te_start) & (pl.col("date_local") <= te_end)).sort("date_local")
    if te.height < 20:
        return None
    n_calib = max(30, int(round(tr.height * CALIB_FRAC)))
    if tr.height - n_calib < 100:
        return None
    fit_df, cal_df = tr.head(tr.height - n_calib), tr.tail(n_calib)

    fit_dates = fit_df["date_local"].to_list()
    cal_dates = cal_df["date_local"].to_list()
    te_dates = te["date_local"].to_list()

    X_fit, y_fit = _arrays(fit_df, OBS_GFS_FEATURES)
    X_cal, y_cal = _arrays(cal_df, OBS_GFS_FEATURES)
    X_te, y_te = _arrays(te, OBS_GFS_FEATURES)
    X_fit[:, _CLIM_IDX] = _clim_vec(climo, fit_dates)
    X_cal[:, _CLIM_IDX] = _clim_vec(climo, cal_dates)
    X_te[:, _CLIM_IDX] = _clim_vec(climo, te_dates)

    cfg = QuantileLgbmConfig(
        feature_columns=tuple(OBS_GFS_FEATURES), coverage=COVERAGE,
        n_estimators=n_estimators, fit_median=True, tau=tau, mode=mode,
    )
    model = fit_quantile_lgbm(X_fit, y_fit, config=cfg)

    q_lo_cal, q_hi_cal = predict_quantiles(model, X_cal)
    q_lo_te, q_hi_te = predict_quantiles(model, X_te)
    cal = conformalize(model, X_cal, y_cal)
    lo_te, hi_te = predict_interval_int(model, cal, X_te)

    # D4 raw crossing on test rows (pre-repair).
    raw_lo_te, raw_hi_te = _raw_quantiles(model, X_te)

    # D5 conformity-score distribution on calib (re-derived; matches conformalize()).
    e_scores = np.maximum(q_lo_cal - y_cal.astype(float), y_cal.astype(float) - q_hi_cal)

    non_calm, high_delta = _regime_masks(tr_start, tr_end, te_dates, risk_df_full)

    return {
        "cp": cp,
        "y": y_te.astype(int),
        "q_lo_cal": q_lo_cal, "q_hi_cal": q_hi_cal, "y_cal": y_cal.astype(int),
        "q_lo_te": q_lo_te, "q_hi_te": q_hi_te,
        "raw_lo_te": raw_lo_te, "raw_hi_te": raw_hi_te,
        "cqr_lo": np.asarray(lo_te, dtype=int), "cqr_hi": np.asarray(hi_te, dtype=int),
        "e_scores": e_scores, "e_correction": float(cal.e_correction),
        "non_calm": non_calm, "high_delta": high_delta,
    }


def _summ(arr) -> dict:
    a = np.asarray(arr, dtype=float)
    if a.size == 0:
        return {"min": None, "median": None, "max": None, "frac_positive": None, "n": 0}
    return {
        "min": round(float(np.min(a)), 4),
        "median": round(float(np.median(a)), 4),
        "max": round(float(np.max(a)), 4),
        "frac_positive": round(float(np.mean(a > 0)), 4),
        "n": int(a.size),
    }


def diagnose_split(panel, split, climo, risk_df_full, tau, mode, n_estimators):
    name, tr_s, tr_e, te_s, te_e = split
    pooled = {k: [] for k in (
        "y", "q_lo_te", "q_hi_te", "raw_lo_te", "raw_hi_te",
        "cqr_lo", "cqr_hi", "non_calm", "high_delta",
    )}
    e_all = []
    e_corr_by_cp = {}
    per_cp = {}
    cp_of_row = []
    # D1 pinball on calib pooled across CPs.
    pin_lo_parts, pin_hi_parts = [], []
    for cp in CPS:
        res = _diagnose_one_cp(panel, cp, tr_s, tr_e, te_s, te_e, climo, risk_df_full,
                               tau, mode, n_estimators)
        if res is None:
            per_cp[cp] = {"status": "thin"}
            continue
        per_cp[cp] = {
            "status": "ok",
            "n_test": int(res["y"].size),
            "e_correction": round(res["e_correction"], 4),
            "d4_crossing_freq": round(crossing_frequency(res["raw_lo_te"], res["raw_hi_te"]), 4),
        }
        for k in pooled:
            pooled[k].append(res[k])
        e_all.append(res["e_scores"])
        e_corr_by_cp[cp] = round(res["e_correction"], 4)
        pin_lo_parts.append((res["q_lo_cal"], res["y_cal"]))
        pin_hi_parts.append((res["q_hi_cal"], res["y_cal"]))
        cp_of_row.extend([cp] * int(res["y"].size))

    if not pooled["y"]:
        return {"split": name, "status": "no_cp"}

    agg = {k: np.concatenate(v) for k, v in pooled.items()}
    cp_arr = np.array(cp_of_row, dtype=object)
    late_mask = cp_arr == LATE_CP
    e_pooled = np.concatenate(e_all)

    # D1 pinball (pooled calib).
    q_lo_cal_all = np.concatenate([p[0] for p in pin_lo_parts])
    y_cal_all = np.concatenate([p[1] for p in pin_lo_parts]).astype(float)
    q_hi_cal_all = np.concatenate([p[0] for p in pin_hi_parts])
    d1 = {
        "pinball_q10": round(pinball_loss(q_lo_cal_all, y_cal_all, 0.10), 4),
        "pinball_q90": round(pinball_loss(q_hi_cal_all, y_cal_all, 0.90), 4),
    }

    # D2 base-band test coverage (round nominal band, no CQR) vs post-CQR coverage.
    base_lo_int = np.round(agg["q_lo_te"]).astype(int)
    base_hi_int = np.round(agg["q_hi_te"]).astype(int)
    d2 = {
        "base_band_coverage": round(_coverage(base_lo_int, base_hi_int, agg["y"]), 4),
        "post_cqr_coverage": round(_coverage(agg["cqr_lo"], agg["cqr_hi"], agg["y"]), 4),
    }

    # D3 per-width-quartile coverage slope on the BASE integer band.
    het = heteroscedasticity_gate(
        base_lo_int, base_hi_int, agg["y"],
        n_bins=HETEROSCED_N_BINS, low=HETEROSCED_COVERAGE_LOW, high=HETEROSCED_COVERAGE_HIGH,
    )
    bins = [b for b in het.bins if b.n > 0]
    if len(bins) >= 2:
        xb = np.array([b.bin_index for b in bins], dtype=float)
        yb = np.array([b.coverage for b in bins], dtype=float)
        slope = float(np.polyfit(xb, yb, 1)[0])
    else:
        slope = float("nan")
    d3 = {
        "coverage_vs_width_slope": round(slope, 4),
        "bins": [{"bin": b.bin_index, "width_lo": b.width_lo, "width_hi": b.width_hi,
                  "coverage": round(b.coverage, 4), "mean_width": round(b.mean_width, 4), "n": b.n}
                 for b in bins],
    }

    # D4 crossing frequency (pooled test).
    d4 = {"crossing_freq": round(crossing_frequency(agg["raw_lo_te"], agg["raw_hi_te"]), 4)}

    # D5 width attribution + E distribution.
    d5 = {
        "width_attribution": width_attribution(agg["q_lo_te"], agg["q_hi_te"], agg["cqr_lo"], agg["cqr_hi"]),
        "e_score_distribution": _summ(e_pooled),
        "e_correction_by_cp": e_corr_by_cp,
    }

    # D6 oracle lower-bound width per stratum (DIAGNOSTIC ONLY).
    masks = {
        "ALL": np.ones(agg["y"].size, dtype=bool),
        "calm": ~agg["non_calm"],
        "non_calm": agg["non_calm"],
        "high_delta": agg["high_delta"],
        "late_cp_23": late_mask,
    }
    d6 = {}
    for st in STRATA:
        m = masks[st]
        n = int(m.sum())
        d6[st] = {
            "n": n,
            "oracle_min_width_80": int(oracle_min_width_80(agg["y"][m])) if n >= 5 else None,
            "cqr_mean_width": round(float(np.mean(agg["cqr_hi"][m] - agg["cqr_lo"][m] + 1)), 4) if n >= 5 else None,
        }

    return {
        "split": name,
        "status": "ok",
        "n_test_pooled": int(agg["y"].size),
        "global_coverage": d2["post_cqr_coverage"],
        "D1_pinball": d1,
        "D2_base_vs_cqr_coverage": d2,
        "D3_width_quartile_slope": d3,
        "D4_crossing": d4,
        "D5_width_and_E": d5,
        "D6_oracle_lower_bound": d6,
        "by_cp": per_cp,
    }


# --------------------------------------------------------------------------- #
# verdict (descriptive evidence, NOT a gate)                                  #
# --------------------------------------------------------------------------- #
def classify_failure(splits) -> dict:
    """Map the pooled evidence to F1/F2/F3 contributions (descriptive only)."""
    ok = [s for s in splits if s.get("status") == "ok"]
    if not ok:
        return {"dominant_failure_mode": "UNKNOWN", "evidence": "no ok splits"}

    def _mean(key_path):
        vals = []
        for s in ok:
            d = s
            for k in key_path:
                d = d[k]
            if d is not None:
                vals.append(float(d))
        return float(np.mean(vals)) if vals else float("nan")

    crossing = _mean(["D4_crossing", "crossing_freq"])
    base_cov = _mean(["D2_base_vs_cqr_coverage", "base_band_coverage"])
    cqr_frac = _mean(["D5_width_and_E", "width_attribution", "cqr_width_fraction"])
    slope = _mean(["D3_width_quartile_slope", "coverage_vs_width_slope"])
    oracle_all = float(np.mean([
        s["D6_oracle_lower_bound"]["ALL"]["oracle_min_width_80"]
        for s in ok if s["D6_oracle_lower_bound"]["ALL"]["oracle_min_width_80"] is not None
    ])) if ok else float("nan")

    contributions = []
    if not np.isnan(crossing) and crossing > 0.05:
        contributions.append(("F2", f"raw quantile crossing {crossing:.3f} > 0.05"))
    if not np.isnan(base_cov) and base_cov > 0.85 and (np.isnan(cqr_frac) or cqr_frac < 0.30):
        contributions.append(("F3", f"base band already over-covers ({base_cov:.3f}) and CQR adds little width (frac={cqr_frac:.3f})"))
    if not np.isnan(slope) and slope > 0.03:
        contributions.append(("F1", f"coverage rises with width (slope {slope:.3f})"))
    if not np.isnan(oracle_all) and oracle_all >= 5:
        contributions.append(("F3", f"oracle 80% floor width {oracle_all:.2f} brackets (integer granularity)"))

    if not contributions:
        dominant = "INCONCLUSIVE"
    else:
        # F3 (structural granularity) dominates when present; else first contributor.
        modes = [c[0] for c in contributions]
        dominant = "F3" if "F3" in modes else modes[0]

    return {
        "dominant_failure_mode": dominant,
        "metrics": {
            "mean_crossing_freq": round(crossing, 4) if not np.isnan(crossing) else None,
            "mean_base_band_coverage": round(base_cov, 4) if not np.isnan(base_cov) else None,
            "mean_cqr_width_fraction": round(cqr_frac, 4) if not np.isnan(cqr_frac) else None,
            "mean_coverage_width_slope": round(slope, 4) if not np.isnan(slope) else None,
            "mean_oracle_floor_width_ALL": round(oracle_all, 4) if not np.isnan(oracle_all) else None,
        },
        "contributions": [{"mode": m, "evidence": e} for m, e in contributions],
        "note": ("Descriptive evidence, not a decision. F3 (integer-granularity floor / CQR-can-only-widen) "
                 "dominates when present because no conformal remedy can narrow below the oracle floor. "
                 "See research/RESEARCH_CQR_OVERCOVERAGE_AND_ALTERNATIVES.md section 6 for the branch."),
    }


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _render_md(report) -> str:
    v = report["verdict"]
    L = [
        "# CQR Over-Coverage Diagnostic (D1-D6) -- Phase 4 post-KILL",
        "",
        f"**Dominant failure mode: {v['dominant_failure_mode']}** (descriptive evidence, NOT a gate or a remedy choice)",
        "",
        f"- git_sha: `{report['git_sha']}`  seed: {report['seed']}  n_estimators: {report['n_estimators']}",
        f"- Companion to the frozen KILL: `reports/calibration/cqr_lightgbm_quantile_v0.{{md,json}}`.",
        "- D6 is an ORACLE lower-bound (peeks at test truth); `oracle_lower_bound_diagnostic_only: true`. Never a model-selection signal.",
        "",
        "## Verdict evidence",
        "",
        "| metric | value |",
        "|--------|-------|",
    ]
    for k, val in v["metrics"].items():
        L.append(f"| {k} | {val} |")
    L += ["", "**Contributions:**"]
    for c in v["contributions"]:
        L.append(f"- `{c['mode']}` -- {c['evidence']}")
    L += ["", f"_{v['note']}_", "", "## Per-split diagnostics", ""]
    for s in report["splits"]:
        if s.get("status") != "ok":
            L.append(f"### {s['split']}: {s.get('status')}")
            continue
        d2 = s["D2_base_vs_cqr_coverage"]
        d5 = s["D5_width_and_E"]["width_attribution"]
        L += [
            f"### {s['split']} (n={s['n_test_pooled']})",
            "",
            f"- D1 pinball: q10={s['D1_pinball']['pinball_q10']}  q90={s['D1_pinball']['pinball_q90']}",
            f"- D2 coverage: base-band={d2['base_band_coverage']}  post-CQR={d2['post_cqr_coverage']}",
            f"- D3 coverage~width slope: {s['D3_width_quartile_slope']['coverage_vs_width_slope']}",
            f"- D4 raw crossing freq: {s['D4_crossing']['crossing_freq']}",
            f"- D5 width: base={d5['mean_base_width']}  cqr={d5['mean_cqr_width']}  cqr_frac={d5['cqr_width_fraction']}  E={s['D5_width_and_E']['e_score_distribution']}",
            "- D6 oracle floor (integer brackets) vs CQR width:",
            "",
            "  | stratum | n | oracle_min_width_80 | cqr_mean_width |",
            "  |---------|---|---------------------|----------------|",
        ]
        for st in STRATA:
            blk = s["D6_oracle_lower_bound"][st]
            L.append(f"  | {st} | {blk['n']} | {blk['oracle_min_width_80']} | {blk['cqr_mean_width']} |")
        L.append("")
    L += ["## Notes", "",
          "- Read-only diagnostic. No gate re-opened, no remedy run (reviewer directive).",
          "- CQR config re-fit identically to the frozen eval (same fit/calib/test slices, seed 42, n_estimators=500).",
          "- F1/F2/F3 mapping per research/RESEARCH_CQR_OVERCOVERAGE_AND_ALTERNATIVES.md section 6.",
          ""]
    return "\n".join(L) + "\n"


def main() -> int:
    import yaml
    import polars as pl  # noqa: F401  (used transitively by helpers)

    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")
    with open(REPO / "nzwn" / "config" / "model.yaml", encoding="ascii") as fh:
        model_cfg = yaml.safe_load(fh)
    tau = float(model_cfg["prob_dist"]["tau"])
    mode = str(model_cfg["prob_dist"]["mode"])
    tmp_min = cfg.tmp_c_int_plausibility.min
    tmp_max = cfg.tmp_c_int_plausibility.max
    cp_op = cfg.cp_operational_utc
    tz = cfg.tz

    print("=== CQR Over-Coverage Diagnostic (D1-D6) ===")
    print(f"  seed={SEED} n_estimators={N_ESTIMATORS} (read-only, no remedy)")

    obs, _ = load_observations(REPO / "NZWN.csv", tmp_min_c=tmp_min, tmp_max_c=tmp_max)
    labels = build_tmax_labels(obs, tz_name=tz, cp_set_utc=cfg.cp_set_utc)
    risk_df_full = build_risk_features(obs, labels, tz, cp_op)

    climo_broad = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))
    thc = fit_tmax_hour_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name=tz)
    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    gfs_snaps = read_snapshots(station=cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root)

    all_dates_full = sorted(d for d in labels["date_local"].unique().to_list()
                            if d is not None and date(2020, 1, 1) <= d <= date(2025, 12, 31))
    panel_gfs = build_training_panel(
        obs, labels, climo=climo_broad, tz_name=tz, cp_set=cfg.cp_set_utc, dates=all_dates_full,
        nwp_snapshots=gfs_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc,
    )

    splits = []
    for split in FULL_SPLITS:
        print(f"[diagnose] {split[0]}")
        climo = _causal_climo(labels, split[2])
        splits.append(diagnose_split(panel_gfs, split, climo, risk_df_full, tau, mode, N_ESTIMATORS))

    verdict = classify_failure(splits)
    print(f"  dominant_failure_mode: {verdict['dominant_failure_mode']}")

    report = {
        "task": "T-11-8-diagnostic",
        "purpose": "D1-D6 over-coverage diagnostic (read-only evidence; no remedy chosen or run)",
        "git_sha": _git_sha(),
        "seed": SEED,
        "deterministic": True,
        "num_threads": 1,
        "n_estimators": N_ESTIMATORS,
        "coverage_target": COVERAGE,
        "oracle_lower_bound_diagnostic_only": True,
        "verdict": verdict,
        "splits": splits,
    }

    out_dir = REPO / "reports" / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cqr_overcoverage_diagnostic.json").write_text(
        json.dumps(report, default=str, ensure_ascii=True, indent=2), encoding="ascii"
    )
    (out_dir / "cqr_overcoverage_diagnostic.md").write_text(_render_md(report), encoding="ascii")
    print(f"[DONE] reports -> {out_dir}/cqr_overcoverage_diagnostic.(json|md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
