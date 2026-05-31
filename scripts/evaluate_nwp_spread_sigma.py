"""T-9-6 NWP-spread sigma feasibility evaluation (read-only).

Question: does a causal CP-available NWP-spread signal exist with quality
to track the realized integer error |y_int - pred_int|?

Verdict criteria (per frozen scope):
  FEASIBLE if a spread column has:
    - CP coverage >= 0.80 in >= 2/3 splits (test days with non-null causal value)
    - Spearman(spread, |error_int|) >= 0.15 (positive) in >= 2/3 splits
    - Mean |error_int| rises across spread quartiles
  Else NOT FEASIBLE with reason.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.baselines.climatology import fit_climatology, fit_tmax_hour_climatology
from core.contracts.station import load_station_config
from core.eval.cv import expanding_walk_forward_splits
from core.features.training_panel import (
    FEATURE_COLUMNS,
    NWP_FEATURE_COLUMNS,
    build_training_panel,
)
from core.ingest.iem_csv import load_observations
from core.ingest.nwp import read_snapshots
from core.ingest.nwp_client import NCEP_GFS
from core.labels.tmax import build_tmax_labels
from core.models.ridge_band import RidgeBandConfig, fit_ridge_band, predict_int as ridge_predict_int

SEED = 42
np.random.seed(SEED)

# Spread columns to evaluate (all that could exist in the panel)
SPREAD_CANDIDATES = (
    "nwp_t2m_at_cp_spread_c",
    "nwp_disagreement_score",
    "nwp_t2m_maxtraj_spread_c",
)

COVERAGE_THRESHOLD = 0.80
SPEARMAN_THRESHOLD = 0.15
SPLITS_REQUIRED_FRAC = 2 / 3


def main() -> int:
    cfg = load_station_config(REPO / "nzwn" / "config" / "station.yaml")

    print("[1/4] Loading observations + labels ...")
    obs, _ = load_observations(
        REPO / "NZWN.csv",
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)

    climo = fit_climatology(labels, train_start=date(2020, 1, 1), train_end=date(2024, 12, 31))

    print("[2/4] Loading NWP snapshots ...")
    nwp_root = REPO / "artifacts" / "raw" / "nwp"
    try:
        nwp_snaps = read_snapshots(
            station=cfg.icao, model=NCEP_GFS, endpoint="s3_grib", out_root=nwp_root
        )
    except Exception as exc:
        print(f"  WARNING: NWP snapshots unavailable ({exc}); reporting thin coverage.")
        nwp_snaps = None

    thc = fit_tmax_hour_climatology(
        labels, train_start=date(2020, 1, 1), train_end=date(2022, 12, 31), tz_name=cfg.tz
    )

    print("[3/4] Building training panel with NWP features ...")
    if nwp_snaps is not None and nwp_snaps.height > 0:
        panel = build_training_panel(
            obs, labels, climo=climo, tz_name=cfg.tz, cp_set=cfg.cp_set_utc,
            nwp_snapshots=nwp_snaps, nwp_models=(NCEP_GFS.id,), tmax_hour_climo=thc,
        )
    else:
        panel = build_training_panel(
            obs, labels, climo=climo, tz_name=cfg.tz, cp_set=cfg.cp_set_utc,
        )
    print(f"  panel rows={panel.height}, columns={panel.columns}")

    # Check which spread candidates actually exist in the panel
    available_spreads = [c for c in SPREAD_CANDIDATES if c in panel.columns]
    if not available_spreads:
        print("  NO spread columns in panel - NWP snapshots absent or panel built without NWP.")
        _write_not_feasible("No NWP spread columns available in panel (snapshots absent or empty).", {})
        return 0

    cp_op = cfg.cp_operational_utc
    splits = expanding_walk_forward_splits(
        history_start=date(2020, 1, 1),
        test_starts=[date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)],
        test_length_days=365,
    )

    print(f"[4/4] Evaluating {len(available_spreads)} spread columns across {len(splits)} splits ...")

    cfg_ridge = RidgeBandConfig(
        feature_columns=tuple(FEATURE_COLUMNS),
        alphas=(0.01, 0.1, 1.0, 10.0, 100.0),
        tau=0.5, mode="linear",
        use_climatology_anchor=True,
    )

    results: dict[str, list[dict]] = {col: [] for col in available_spreads}

    for s in splits:
        print(f"  Split: {s.name}")
        sub = panel.filter(panel["cp"] == cp_op)
        train = sub.filter(
            (sub["date_local"] >= s.train_start) & (sub["date_local"] <= s.train_end)
        )
        test = sub.filter(
            (sub["date_local"] >= s.test_start) & (sub["date_local"] <= s.test_end)
        )

        # Need valid targets and basic features for Ridge
        feat_cols = list(FEATURE_COLUMNS)
        train_ok = train.drop_nulls(subset=feat_cols + ["target_tmax_int"])
        test_ok = test.drop_nulls(subset=feat_cols + ["target_tmax_int"])

        if train_ok.height < 50 or test_ok.height < 10:
            print(f"    Insufficient rows (train={train_ok.height}, test={test_ok.height}), skip")
            for col in available_spreads:
                results[col].append({
                    "split": s.name, "cp_coverage": 0.0,
                    "spearman": None, "quartile_means": None,
                    "n_test": int(test_ok.height), "n_with_spread": 0,
                })
            continue

        # Fit Ridge on train to get pred_int on test
        X_train = np.column_stack([train_ok[c].to_numpy().astype(float) for c in feat_cols])
        y_train = train_ok["target_tmax_int"].to_numpy().astype(int)
        X_test = np.column_stack([test_ok[c].to_numpy().astype(float) for c in feat_cols])
        y_test = test_ok["target_tmax_int"].to_numpy().astype(int)

        # Causal climo for Ridge anchor
        train_labels = train_ok.select(["date_local", "target_tmax_int"]).rename(
            {"target_tmax_int": "tmax_int"}
        ).with_columns(pl.lit(True).alias("day_complete"))
        split_climo = fit_climatology(train_labels, train_start=s.train_start, train_end=s.train_end)
        clim_train = np.array([float(split_climo.tmax_dec_for(d)) for d in train_ok["date_local"].to_list()])
        clim_test = np.array([float(split_climo.tmax_dec_for(d)) for d in test_ok["date_local"].to_list()])

        ridge = fit_ridge_band(X_train, y_train, config=cfg_ridge, clim_train=clim_train)
        pred_int = ridge_predict_int(ridge, X_test, clim=clim_test)
        abs_error = np.abs(y_test - pred_int)

        # Evaluate each spread column
        for col in available_spreads:
            spread_vals = test_ok[col].to_numpy().astype(float)
            valid_mask = ~np.isnan(spread_vals)
            n_valid = int(valid_mask.sum())
            n_total = int(test_ok.height)
            cp_coverage = n_valid / n_total if n_total > 0 else 0.0

            if n_valid < 10:
                results[col].append({
                    "split": s.name, "cp_coverage": cp_coverage,
                    "spearman": None, "quartile_means": None,
                    "n_test": n_total, "n_with_spread": n_valid,
                    "constant": False,
                })
                continue

            spread_valid = spread_vals[valid_mask]
            error_valid = abs_error[valid_mask].astype(float)

            # Detect constant spread (single-model -> zero variance)
            is_constant = bool(np.std(spread_valid) < 1e-12)
            if is_constant:
                rho = float("nan")
            else:
                rho, _ = spearmanr(spread_valid, error_valid)

            # Quartile analysis
            if is_constant:
                # All values identical -> all in one bin, quartile analysis meaningless
                mean_err = float(np.mean(error_valid))
                quartile_means = [mean_err, None, None, None]
            else:
                quartiles = np.quantile(spread_valid, [0.25, 0.5, 0.75])
                q_labels = np.digitize(spread_valid, quartiles)  # 0,1,2,3
                quartile_means = []
                for q in range(4):
                    mask_q = q_labels == q
                    if mask_q.sum() > 0:
                        quartile_means.append(float(np.mean(error_valid[mask_q])))
                    else:
                        quartile_means.append(None)

            results[col].append({
                "split": s.name, "cp_coverage": round(cp_coverage, 4),
                "spearman": round(float(rho), 4) if not np.isnan(rho) else None,
                "quartile_means": quartile_means,
                "n_test": n_total, "n_with_spread": n_valid,
                "constant": is_constant,
            })
            print(f"    {col}: coverage={cp_coverage:.3f}, spearman={rho:.4f}, "
                  f"quartile_err={[f'{x:.2f}' if x else 'N/A' for x in quartile_means]}")

    # Determine verdict
    n_splits = len(splits)
    n_required = max(2, int(np.ceil(n_splits * SPLITS_REQUIRED_FRAC)))
    best_col = None
    best_score = -1.0
    col_verdicts = {}

    for col in available_spreads:
        col_splits = results[col]
        n_cov_pass = sum(1 for r in col_splits if r["cp_coverage"] >= COVERAGE_THRESHOLD)
        n_spear_pass = sum(
            1 for r in col_splits
            if r["spearman"] is not None and r["spearman"] >= SPEARMAN_THRESHOLD
        )
        # Check monotonic-ish: error rises across quartiles in >=2/3 splits
        n_mono = 0
        for r in col_splits:
            qm = r["quartile_means"]
            if qm and all(x is not None for x in qm):
                if qm[3] > qm[0]:  # Q4 error > Q1 error
                    n_mono += 1

        feasible = (n_cov_pass >= n_required and n_spear_pass >= n_required and n_mono >= n_required)
        col_verdicts[col] = {
            "n_coverage_pass": n_cov_pass,
            "n_spearman_pass": n_spear_pass,
            "n_monotonic_pass": n_mono,
            "feasible": feasible,
        }
        # Track best by mean spearman across valid splits
        valid_spears = [r["spearman"] for r in col_splits if r["spearman"] is not None]
        mean_spear = float(np.mean(valid_spears)) if valid_spears else -1.0
        if feasible and mean_spear > best_score:
            best_score = mean_spear
            best_col = col

    any_feasible = any(v["feasible"] for v in col_verdicts.values())

    # Build output
    report_data = {
        "task": "T-9-6",
        "title": "NWP-spread sigma feasibility",
        "n_splits": n_splits,
        "n_required": n_required,
        "coverage_threshold": COVERAGE_THRESHOLD,
        "spearman_threshold": SPEARMAN_THRESHOLD,
        "spread_columns_evaluated": available_spreads,
        "per_column": {},
        "verdict": "FEASIBLE" if any_feasible else "NOT FEASIBLE",
        "best_column": best_col,
        "reason": None,
        "recommendation": None,
    }

    for col in available_spreads:
        report_data["per_column"][col] = {
            "splits": results[col],
            "summary": col_verdicts[col],
        }

    if any_feasible:
        report_data["recommendation"] = (
            f"Column '{best_col}' passes all feasibility criteria. "
            "Recommend a follow-up INTEGER-NATIVE calibrator conditioned on this spread "
            "(separate pre-registration, not built here)."
        )
    else:
        # Determine reason - check for constant spread (single-model root cause)
        reasons = []
        all_constant = all(
            all(r.get("constant", False) for r in results[col])
            for col in available_spreads
        )
        if all_constant:
            reasons.append(
                "All spread columns are CONSTANT (zero variance) across all splits. "
                "Root cause: panel uses a single NWP model (NCEP GFS only); "
                "inter-model spread requires >=2 models but only 1 is available in "
                "the local snapshot archive. The NWP-spread axis cannot be evaluated "
                "without a multi-model ensemble."
            )
        else:
            for col in available_spreads:
                v = col_verdicts[col]
                if v["n_coverage_pass"] < n_required:
                    reasons.append(f"{col}: thin coverage ({v['n_coverage_pass']}/{n_required} splits pass)")
                elif v["n_spearman_pass"] < n_required:
                    reasons.append(f"{col}: no correlation ({v['n_spearman_pass']}/{n_required} splits pass spearman>=0.15)")
                elif v["n_monotonic_pass"] < n_required:
                    reasons.append(f"{col}: error does not rise with spread ({v['n_monotonic_pass']}/{n_required} splits)")
        report_data["reason"] = "; ".join(reasons) if reasons else "No spread column meets all criteria."

    # Write reports
    out_dir = REPO / "reports" / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "nwp_spread_sigma_feasibility.json"
    json_path.write_text(
        json.dumps(report_data, default=str, ensure_ascii=True, indent=2),
        encoding="ascii",
    )

    md_path = out_dir / "nwp_spread_sigma_feasibility.md"
    md_path.write_text(_render_md(report_data), encoding="ascii")

    print(f"\n{'='*60}")
    print(f"VERDICT: {report_data['verdict']}")
    if best_col:
        print(f"Best column: {best_col}")
    if report_data["reason"]:
        print(f"Reason: {report_data['reason']}")
    if report_data["recommendation"]:
        print(f"Recommendation: {report_data['recommendation']}")
    print(f"Reports written: {json_path}, {md_path}")
    print(f"{'='*60}")
    return 0


def _write_not_feasible(reason: str, col_data: dict) -> None:
    """Write NOT FEASIBLE report when no spread data is available."""
    out_dir = REPO / "reports" / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_data = {
        "task": "T-9-6",
        "title": "NWP-spread sigma feasibility",
        "verdict": "NOT FEASIBLE",
        "reason": reason,
        "best_column": None,
        "recommendation": None,
        "per_column": col_data,
    }
    (out_dir / "nwp_spread_sigma_feasibility.json").write_text(
        json.dumps(report_data, default=str, ensure_ascii=True, indent=2), encoding="ascii"
    )
    (out_dir / "nwp_spread_sigma_feasibility.md").write_text(
        _render_md(report_data), encoding="ascii"
    )
    print(f"\nVERDICT: NOT FEASIBLE - {reason}")
    print(f"Reports written to reports/calibration/")


def _render_md(data: dict) -> str:
    lines = [
        "# NWP-Spread Sigma Feasibility Report (T-9-6)",
        "",
        f"**Verdict: {data['verdict']}**",
        "",
    ]
    if data.get("reason"):
        lines.append(f"Reason: {data['reason']}")
        lines.append("")
    if data.get("recommendation"):
        lines.append(f"Recommendation: {data['recommendation']}")
        lines.append("")
    lines.extend([
        "## Criteria",
        "",
        f"- CP coverage >= {data.get('coverage_threshold', 0.80)}",
        f"- Spearman(spread, |error_int|) >= {data.get('spearman_threshold', 0.15)} (positive)",
        f"- Mean |error_int| rises across spread quartiles (Q4 > Q1)",
        f"- Required in >= {data.get('n_required', 2)}/{data.get('n_splits', 3)} splits",
        "",
    ])
    per_col = data.get("per_column", {})
    if per_col:
        lines.append("## Per-column results")
        lines.append("")
        for col, info in per_col.items():
            summary = info.get("summary", {})
            lines.append(f"### {col}")
            lines.append("")
            lines.append(f"- Coverage passes: {summary.get('n_coverage_pass', '?')}/{data.get('n_required', 2)}")
            lines.append(f"- Spearman passes: {summary.get('n_spearman_pass', '?')}/{data.get('n_required', 2)}")
            lines.append(f"- Monotonic passes: {summary.get('n_monotonic_pass', '?')}/{data.get('n_required', 2)}")
            lines.append(f"- Feasible: {summary.get('feasible', False)}")
            lines.append("")
            splits_data = info.get("splits", [])
            if splits_data:
                lines.append("| split | CP coverage | n_with_spread | Spearman | Q1 err | Q2 err | Q3 err | Q4 err |")
                lines.append("|-------|-------------|---------------|----------|--------|--------|--------|--------|")
                for r in splits_data:
                    qm = r.get("quartile_means") or [None]*4
                    qm_str = [f"{x:.2f}" if x is not None else "-" for x in qm]
                    sp = f"{r['spearman']:.4f}" if r.get("spearman") is not None else "-"
                    lines.append(
                        f"| {r['split']} | {r['cp_coverage']:.3f} | "
                        f"{r.get('n_with_spread', 0)} | {sp} | "
                        f"{qm_str[0]} | {qm_str[1]} | {qm_str[2]} | {qm_str[3]} |"
                    )
                lines.append("")
    if data.get("best_column"):
        lines.extend([
            "## Recommendation",
            "",
            f"Best column: `{data['best_column']}`",
            "",
            "Follow-up: build an INTEGER-NATIVE calibrator conditioned on this spread",
            "(separate pre-registration required; not built in this feasibility front).",
            "",
        ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
