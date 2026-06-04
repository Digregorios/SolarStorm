"""CLI entry point: tmax ingest | baselines | leaderboard | eda.

Every command that produces output writes a versioned artifact to reports/ (P5).
Stdout is an echo, not the authoritative record.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl
import typer

from solarstorm._config import SEED
from solarstorm.data._iem import fetch_iem_asos
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
    climo = fit_climatology(
        complete.filter(pl.col("date_local") <= train_end),
        train_start=dt.date(2009, 1, 1),
        train_end=train_end,
    )

    results: list[LadderResult] = []
    for row in recent.iter_rows(named=True):
        d = row["date_local"]
        truth = row["tmax_int"]

        for cp_str in ["20:00", "21:00", "22:00", "23:00"]:
            cp_code = cp_str.replace(":", "")
            kcp_col = f"k_cp__cp_{cp_code}"
            kcp = row.get(kcp_col)
            if kcp is None:
                continue

            # L0: persistence
            results.append(LadderResult(
                level="L0", name="persistence", cp=cp_str,
                mae=abs(kcp - truth), n=1,
            ))

            # L1: dminus1
            dminus1 = row.get("tmax_int")  # placeholder — needs previous day lookup
            # L2: climatology
            clim_pred = round(climo.tmax_dec_for(d))
            results.append(LadderResult(
                level="L2", name="climatology_doy", cp=cp_str,
                mae=abs(clim_pred - truth), n=1,
            ))

    # Build and export
    board = build_leaderboard(
        results=results, segments={},
        window_start=window_start, window_end=today - dt.timedelta(days=1),
    )
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
