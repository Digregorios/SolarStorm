"""CLI entry point: tmax ingest | baselines | leaderboard | eda.

Every command that produces output writes a versioned artifact to reports/ (P5).
Stdout is an echo, not the authoritative record.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import polars as pl
import typer

from solarstorm._config import SEED
from solarstorm.data._iem import fetch_iem_asos
from solarstorm.data._settlement import integer_settlement
from solarstorm.data._metar import parse_tmp_c_int_from_row
from solarstorm.data._obs import persist_obs
from solarstorm.data._labels import build_tmax_labels, DayCompleteParams
from solarstorm.data._calendar import cp_to_utc
from solarstorm.data._settlement import bracket_for, flip_risk
from solarstorm.baselines._climatology import fit_climatology
from solarstorm.baselines._empirical import fit_empirical_conditional
from solarstorm.baselines._ladder import LadderResult, best_null_for_cp
from solarstorm.eval._leaderboard import build_leaderboard, export_leaderboard
from solarstorm.eda._hypotheses import Hypothesis
from solarstorm.eda._catalog import SEED_HYPOTHESES
from solarstorm.features.builder import build_features, build_coverage_manifest, BLOCKED_FEATURES
from solarstorm.eda._validate import validate_hypotheses, _fit_ols_challenger

app = typer.Typer(help="SolarStorm — intraday Tmax forecaster for NZWN")
CACHE_DIR = Path("./.cache/iem")
REPORTS_DIR = Path("./reports")


@app.command()
def ingest(
    station: str = typer.Option("NZWN", help="ICAO station code"),
    start: str = typer.Option("2009-01-01", help="Start date YYYY-MM-DD"),
    end: str = typer.Option("2026-06-03", help="End date YYYY-MM-DD"),
):
    """Backfill METAR observations from IEM ASOS."""
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    df = fetch_iem_asos(station, s, e, cache_dir=CACHE_DIR)
    print(f"Ingested {df.height:,} rows ({station}, {start} to {end})")

    stats = {"n_total": 0, "n_ok": 0, "n_imputed": 0, "n_missing": 0}
    tmp_c_int_vals: list[int | None] = []
    dq_vals: list[str] = []
    for row in df.iter_rows(named=True):
        tt, _, dq, _ = parse_tmp_c_int_from_row(row["metar"], row.get("tmpf"))
        stats["n_total"] += 1
        stats[f"n_{dq}"] += 1
        tmp_c_int_vals.append(tt)
        dq_vals.append(dq)
    print(f"Parse stats: {stats}")

    df = df.with_columns(
        pl.Series("tmp_c_int", tmp_c_int_vals, dtype=pl.Int64),
        pl.Series("dq_tmp_c_int", dq_vals, dtype=pl.Utf8),
    )

    data_dir = Path("./data")
    data_dir.mkdir(exist_ok=True)
    df = persist_obs(df, data_dir)

    labels = build_tmax_labels(df, DayCompleteParams())
    complete = labels.filter(pl.col("day_complete"))
    print(f"Labels: {labels.height} days, {complete.height} complete")

    labels.write_parquet(data_dir / "labels.parquet")
    print(f"Saved labels to {data_dir / 'labels.parquet'}")


@app.command()
def baselines(
    labels_path: str = typer.Option("./data/labels.parquet", help="Path to labels parquet"),
):
    """Fit all baselines and print a summary."""
    labels = pl.read_parquet(labels_path)
    complete = labels.filter(pl.col("day_complete"))

    print(f"Loaded {complete.height} complete days")

    climo = fit_climatology(
        complete,
        train_start=dt.date(2009, 1, 1),
        train_end=dt.date(2025, 12, 31),
    )
    print(f"Climatology: {climo.n_train_days} training days")

    emp = fit_empirical_conditional(
        complete,
        train_window=(dt.date(2009, 1, 1), dt.date(2025, 12, 31)),
    )
    print("Empirical conditional fitted")

    print("\nBaselines ready. Run 'leaderboard' to evaluate.")


@app.command()
def features(
    obs_path: str = typer.Option("./data/obs.parquet", help="Path to obs parquet"),
    labels_path: str = typer.Option("./data/labels.parquet", help="Path to labels parquet"),
    output_dir: str = typer.Option("./data", help="Output directory for features.parquet"),
):
    """Compute causal feature table from obs + labels (bridge P3)."""
    obs = pl.read_parquet(obs_path)
    labels = pl.read_parquet(labels_path)
    print(f"Loaded {obs.height} obs rows, {labels.height} label rows")

    result = build_features(obs, labels)
    out = Path(output_dir)
    out.mkdir(exist_ok=True)
    result.write_parquet(out / "features.parquet")
    print(f"Features: {result.height} rows, {len(result.columns)} columns")

    # Coverage manifest
    manifest = build_coverage_manifest(result)
    today_iso = dt.date.today().isoformat()
    report_dir = REPORTS_DIR / today_iso
    report_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = report_dir / "feature_coverage.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Summary
    n_computable = sum(1 for v in manifest.values() if v["status"] == "computable")
    n_blocked = sum(1 for v in manifest.values() if v["status"] == "BLOCKED")
    print(f"Coverage manifest: {n_computable} computable, {n_blocked} BLOCKED")
    print(f"  {manifest_path}")


@app.command()
def validate(
    features_path: str = typer.Option("./data/features.parquet", help="Path to features parquet"),
    labels_path: str = typer.Option("./data/labels.parquet", help="Path to labels parquet"),
):
    """Run hypothesis validation harness (bridge P3)."""
    features = pl.read_parquet(features_path)
    labels = pl.read_parquet(labels_path)
    print(f"Loaded {features.height} feature rows, {labels.height} label rows")

    all_results, contract = validate_hypotheses(
        features, labels, SEED_HYPOTHESES,
    )
    print(f"Validation complete: {contract['n_validated']} validated, "
          f"{contract['n_rejected']} rejected")

    today_iso = dt.date.today().isoformat()
    report_dir = REPORTS_DIR / today_iso
    report_dir.mkdir(parents=True, exist_ok=True)

    # ---- JSON export ----
    results_json = []
    for r in all_results:
        d = {
            "id": r.id,
            "feature_column": r.feature_column,
            "cp": r.cp,
            "regime": r.regime,
            "effect_size": r.effect_size,
            "ci_lo": r.ci_lo,
            "ci_hi": r.ci_hi,
            "p_value": r.p_value,
            "fdr_adjusted": r.fdr_adjusted,
            "passes": r.passes,
            "n_days": r.n_days,
            "status": r.status,
            "blocked_reason": r.blocked_reason,
        }
        if r.gate_results:
            d["gates"] = {
                k: {"passed": g.passed, "status": g.status, "detail": g.detail}
                for k, g in r.gate_results.items()
            }
        results_json.append(d)

    json_path = report_dir / "hypothesis_results.json"
    json_path.write_text(json.dumps(results_json, indent=2), encoding="utf-8")

    # ---- Markdown table ----
    md_lines = [
        f"# Hypothesis Validation Results — {today_iso}",
        "",
        "| id | feature | cp | regime | effect_size | ci_lo | ci_hi | p_value | fdr | passes | gates | status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in all_results:
        fdr = "Y" if r.fdr_adjusted else "N"
        passes = "Y" if r.passes else "N"
        gates_str = " ".join(
            f"{k}:{g.status}" for k, g in (r.gate_results or {}).items()
        )
        es = f"{r.effect_size:.4f}" if r.effect_size is not None else ""
        clo = f"{r.ci_lo:.4f}" if r.ci_lo is not None else ""
        chi = f"{r.ci_hi:.4f}" if r.ci_hi is not None else ""
        pv = f"{r.p_value:.6f}" if r.p_value is not None else ""
        md_lines.append(
            f"| {r.id} | {r.feature_column} | {r.cp} | {r.regime} "
            f"| {es} | {clo} | {chi} | {pv} "
            f"| {fdr} | {passes} | {gates_str} | {r.status} |"
        )

    md_path = report_dir / "hypothesis_results.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    # ---- Validated contract ----
    contract_path = report_dir / "validated_feature_contract.json"
    contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")

    print(f"\nExported to {report_dir}:")
    print(f"  {json_path.name}")
    print(f"  {md_path.name}")
    print(f"  {contract_path.name}")
    print(f"\nValidated: {contract.get('n_validated', 0)}  "
          f"Rejected: {contract.get('n_rejected', 0)}  "
          f"BLOCKED: {len(contract.get('blocked', []))}")


@app.command()
def leaderboard(
    labels_path: str = typer.Option("./data/labels.parquet", help="Path to labels parquet"),
    window_days: int = typer.Option(30, help="Recent window size in days"),
):
    """Evaluate all baselines on recent window and export leaderboard (P5)."""
    labels = pl.read_parquet(labels_path)
    complete = labels.filter(pl.col("day_complete"))

    today = dt.date.today()
    window_start = today - dt.timedelta(days=window_days)
    recent = complete.filter(
        pl.col("date_local").is_between(window_start, today - dt.timedelta(days=1))
    )

    if recent.height == 0:
        print(f"No complete days in window [{window_start}, {today})")
        raise typer.Exit(1)

    print(f"Evaluating {recent.height} days in window [{window_start}, {today})")

    # Fit baselines on all data up to window_start
    train_end = window_start - dt.timedelta(days=1)
    train_labels = complete.filter(pl.col("date_local") <= train_end)

    climo = fit_climatology(
        train_labels,
        train_start=dt.date(2009, 1, 1),
        train_end=train_end,
    )

    # ---- L4 empirical conditional ----
    history_start = complete["date_local"].min()
    emp = fit_empirical_conditional(
        train_labels,
        train_window=(history_start, train_end),
    )
    support_k = sorted(complete["tmax_int"].unique().to_list())

    # ---- Date-to-tmax lookup for L1 (dminus1) ----
    tmax_by_date: dict[dt.date, int] = {
        row["date_local"]: row["tmax_int"]
        for row in complete.iter_rows(named=True)
    }

    # ---- Build regime lookup for segments ----
    regime_lookup: dict[tuple[dt.date, str], str] = {}
    features_path = Path("./data/features.parquet")
    if features_path.exists():
        feats_df = pl.read_parquet(features_path)
        for frow in feats_df.select(["date_local", "cp", "regime_label"]).iter_rows(named=True):
            regime_lookup[(frow["date_local"], frow["cp"])] = frow["regime_label"] or "unknown"

    # ---- Evaluate all baselines per-row (with regime tracking) ----
    results: list[LadderResult] = []
    regime_errors: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    n_missing_dminus1: int = 0
    for row in recent.iter_rows(named=True):
        d = row["date_local"]
        truth = row["tmax_int"]

        for cp_str in ["20:00", "21:00", "22:00", "23:00"]:
            cp_code = cp_str.replace(":", "")
            kcp_col = f"k_cp__cp_{cp_code}"
            kcp = row.get(kcp_col)
            if kcp is None:
                continue

            kcp_int = int(kcp)
            regime = regime_lookup.get((d, cp_str), "unknown")
            error_l0 = kcp_int - truth

            # L0: persistence
            results.append(LadderResult(
                level="L0", name="persistence", cp=cp_str,
                mae=abs(error_l0), rmse=error_l0**2, bias=error_l0,
                bracket_match=1.0 if kcp_int == truth else 0.0, n=1,
            ))
            regime_errors[("L0", "persistence", cp_str, regime)].append(abs(error_l0))

            # L1: dminus1
            prev_day = d - dt.timedelta(days=1)
            tmax_dminus1 = tmax_by_date.get(prev_day)
            if tmax_dminus1 is not None:
                error_l1 = tmax_dminus1 - truth
                results.append(LadderResult(
                    level="L1", name="dminus1", cp=cp_str,
                    mae=abs(error_l1), rmse=error_l1**2, bias=error_l1,
                    bracket_match=1.0 if tmax_dminus1 == truth else 0.0, n=1,
                ))
                regime_errors[("L1", "dminus1", cp_str, regime)].append(abs(error_l1))
            else:
                n_missing_dminus1 += 1

            # L2: climatology
            clim_pred = integer_settlement(climo.tmax_dec_for(d))
            error_l2 = clim_pred - truth
            results.append(LadderResult(
                level="L2", name="climatology_doy", cp=cp_str,
                mae=abs(error_l2), rmse=error_l2**2, bias=error_l2,
                bracket_match=1.0 if clim_pred == truth else 0.0, n=1,
            ))
            regime_errors[("L2", "climatology_doy", cp_str, regime)].append(abs(error_l2))

            # L4: empirical conditional (mode of distribution)
            dist, source = emp.predict_dist(
                month=d.month, cp=str(cp_str), k_cp=kcp_int,
                support_k=support_k,
            )
            l4_p50 = max(dist, key=dist.get)
            error_l4 = l4_p50 - truth
            results.append(LadderResult(
                level="L4", name="empirical_conditional", cp=cp_str,
                mae=abs(error_l4), rmse=error_l4**2, bias=error_l4,
                bracket_match=1.0 if l4_p50 == truth else 0.0, n=1,
                fallback_rate=0.0 if source == "conditional" else 1.0,
            ))
            regime_errors[("L4", "empirical_conditional", cp_str, regime)].append(abs(error_l4))

    # ---- Aggregate per-row results into per-(level, name, cp) summaries ----
    from solarstorm.baselines._ladder import aggregate_results
    aggregated = aggregate_results(results)

    if n_missing_dminus1 > 0:
        print(f"L1 (dminus1): {n_missing_dminus1} rows skipped (previous day data unavailable)")

    # ---- Build segments: MAE by regime for each baseline × CP ----
    segments: dict[str, list[LadderResult]] = {}
    for (level, name, cp, regime), errors in sorted(regime_errors.items()):
        n_regime = len(errors)
        if n_regime > 0:
            segments.setdefault(regime, []).append(LadderResult(
                level=level, name=name, cp=cp,
                mae=sum(errors) / n_regime, n=n_regime,
            ))

    # ---- Gates: G1-G5 for each aggregated baseline × CP ----
    from solarstorm.eval._gates import apply_all_gates
    gates_dict: dict[str, dict[str, dict]] = {}
    best_null_mae_by_cp: dict[str, float] = {}
    for r in aggregated:
        if r.level != "feature":
            prev_best = best_null_mae_by_cp.get(r.cp, float("inf"))
            if r.mae < prev_best:
                best_null_mae_by_cp[r.cp] = r.mae

    for r in aggregated:
        if r.level == "feature":
            continue
        best_mae = best_null_mae_by_cp.get(r.cp, r.mae)
        gate_results = apply_all_gates(
            model_mae=r.mae,
            best_null_mae=best_mae,
            cp=r.cp,
            fallback_rate=r.fallback_rate or 0.0,
            p50_mode_share=r.p50_mode_share,
            corr_diff=r.corr_diff,
            per_cp_passed=r.mae <= best_mae,
        )
        gates_dict.setdefault(r.cp, {})[f"{r.level}_{r.name}"] = {
            g.gate: {"passed": g.passed, "status": g.status, "detail": g.detail}
            for g in gate_results.values()
        }

    # ---- Build and export ----
    board = build_leaderboard(
        results=aggregated, segments=segments, gates=gates_dict,
        window_start=window_start, window_end=today - dt.timedelta(days=1),
    )

    # ---- Baseline+Feature Nulls ----
    today_iso = dt.date.today().isoformat()
    contract_path = REPORTS_DIR / today_iso / "validated_feature_contract.json"
    features_path = Path("./data/features.parquet")

    if contract_path.exists() and features_path.exists():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        features_df = pl.read_parquet(features_path)
        feature_rows: list[LadderResult] = []

        for vf in contract.get("validated_features", []):
            fc = vf["feature_column"]
            cp_str = vf["cp"]

            # Skip regime-specific results; use the "all" aggregate
            if vf.get("regime", "all") != "all":
                continue

            # Fit OLS challenger on training data
            train_feats_cp = features_df.filter(
                (pl.col("date_local") <= train_end) & (pl.col("cp") == cp_str)
            )
            ols = _fit_ols_challenger(train_feats_cp, complete, fc, cp_str)
            if ols is None:
                continue

            intercept, slope = ols
            k_col = f"k_cp__cp_{cp_str.replace(':', '')}"

            errors: list[float] = []
            preds: list[float] = []
            truths: list[float] = []
            base_preds: list[float] = []

            for trow in recent.iter_rows(named=True):
                td = trow["date_local"]
                truth_val = trow["tmax_int"]
                kcp_val = trow.get(k_col)
                if kcp_val is None:
                    continue

                feat_row = features_df.filter(
                    (pl.col("date_local") == td) & (pl.col("cp") == cp_str)
                )
                if feat_row.height == 0:
                    continue

                feat_np = feat_row[fc].to_numpy()
                if len(feat_np) == 0 or np.isnan(float(feat_np[0])):
                    continue

                pred_rw = intercept + slope * float(feat_np[0])
                pred_tmax = integer_settlement(kcp_val + pred_rw)

                errors.append(abs(pred_tmax - truth_val))
                preds.append(float(pred_tmax))
                truths.append(float(truth_val))
                base_preds.append(float(kcp_val))

            if len(errors) >= 5:
                mean_ae = sum(errors) / len(errors)

                # corr_diff
                pa = np.array(preds)
                ta = np.array(truths)
                ba = np.array(base_preds)
                mask = ~(np.isnan(pa) | np.isnan(ta))
                if mask.sum() > 2:
                    r_model = float(np.corrcoef(pa[mask], ta[mask])[0, 1])
                    r_base = float(np.corrcoef(ba[mask], ta[mask])[0, 1])
                    cdiff = r_model - r_base
                else:
                    cdiff = None

                feature_rows.append(LadderResult(
                    level="feature", name=fc, cp=cp_str,
                    mae=mean_ae, n=len(errors), corr_diff=cdiff,
                ))

        if feature_rows:
            board["feature_nulls"] = [
                {"name": r.name, "cp": r.cp, "mae": r.mae, "n": r.n,
                 "corr_diff": r.corr_diff}
                for r in feature_rows
            ]

    json_path, md_path = export_leaderboard(board, REPORTS_DIR / "leaderboard")
    print(f"Leaderboard exported:")
    print(f"  {json_path}")
    print(f"  {md_path}")

    # Print summary
    print(f"\n{board['summary']}")


@app.command()
def eda(
    labels_path: str = typer.Option("./data/labels.parquet", help="Path to labels parquet"),
):
    """Run hypothesis catalog and export results (P5)."""
    hypotheses = SEED_HYPOTHESES
    results = []

    for h in hypotheses:
        # Placeholder: actual test runs through walk-forward harness
        result = {
            "id": h.id,
            "description": h.description,
            "feature_column": h.feature_column,
            "source": h.source,
            "status": "pending",  # Will be filled by actual EDA run
        }
        results.append(result)

    out = REPORTS_DIR / "hypotheses"
    out.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    json_path = out / f"{today}-hypotheses.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    md_lines = ["# Hypothesis Catalog", f"Generated: {today}", ""]
    for r in results:
        md_lines.append(f"- **{r['id']}** [{r['status']}]: {r['description']} (source: {r['source']})")
    md_path = out / f"{today}-hypotheses.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"Hypothesis results exported to {out}")
    print(f"  {json_path}")
    print(f"  {md_path}")


if __name__ == "__main__":
    app()
