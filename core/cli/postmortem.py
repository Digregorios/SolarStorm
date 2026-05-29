"""CLI: tmax postmortem (REQ-OPS-4)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from core.contracts.station import load_station_config
from core.ingest.iem_csv import load_observations
from core.io.logging import log_event, new_run_id
from core.labels.tmax import build_tmax_labels


def run(
    station_yaml: Path = typer.Option(Path("nzwn/config/station.yaml"), "--station-config"),
    csv: Path = typer.Option(Path("NZWN.csv"), "--csv"),
    target_date: str = typer.Option(..., "--date"),
    forecast_path: Path | None = typer.Option(None, "--forecast", help="forecast JSON to compare"),
    out_root: Path = typer.Option(Path("reports/postmortem"), "--out-root"),
) -> None:
    """Compare forecast vs truth and write reports/postmortem/<date>.md."""
    new_run_id()
    cfg = load_station_config(station_yaml)
    d = date.fromisoformat(target_date)
    obs, _ = load_observations(
        csv,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    row = labels.filter(labels["date_local"] == d)
    if row.height == 0:
        raise typer.BadParameter(f"No labels for {d}")
    truth = int(row["tmax_int"][0]) if row["tmax_int"][0] is not None else None
    day_complete = bool(row["day_complete"][0])
    section_lines: list[str] = []
    section_lines.append(f"# Postmortem {d.isoformat()} - {cfg.icao}\n")
    section_lines.append(f"- truth_tmax_int: {truth}")
    section_lines.append(f"- day_complete: {day_complete}\n")
    if forecast_path is not None and forecast_path.exists():
        with open(forecast_path, encoding="ascii") as fh:
            fc = json.load(fh)
        p50 = fc.get("p50_int")
        ic_low = fc.get("ic80_low_int")
        ic_high = fc.get("ic80_high_int")
        section_lines.append("## Forecast")
        section_lines.append(f"- run_id: {fc.get('run_id')}")
        section_lines.append(f"- p50_int: {p50}")
        section_lines.append(f"- IC80: [{ic_low}, {ic_high}]")
        if truth is not None:
            inside = ic_low is not None and ic_high is not None and ic_low <= truth <= ic_high
            err = (p50 - truth) if (p50 is not None and truth is not None) else None
            section_lines.append(f"- truth_in_IC80: {inside}")
            section_lines.append(f"- p50_minus_truth: {err}")
        prob_dist = fc.get("prob_dist", {})
        if prob_dist and truth is not None:
            section_lines.append(f"- P(Tmax=truth): {prob_dist.get(str(truth), 0.0):.4f}")
            # bracket-match @ coverage 25/50/75/100
            section_lines.append("\n## bracket_match @ coverage")
            section_lines.append("| coverage | match |")
            section_lines.append("|----------|-------|")
            sorted_items = sorted(prob_dist.items(), key=lambda kv: -kv[1])
            cov_targets = [0.25, 0.5, 0.75, 1.0]
            for cov in cov_targets:
                cum = 0.0
                covered = []
                for k_str, p in sorted_items:
                    cum += p
                    covered.append(int(k_str))
                    if cum >= cov:
                        break
                hit = int(truth in covered)
                section_lines.append(f"| {int(cov*100)}% | {hit} |")
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / f"{d.isoformat()}.md"
    out_path.write_text("\n".join(section_lines) + "\n", encoding="ascii")
    log_event("postmortem", "postmortem.done", extra={"date_local": d.isoformat()})
    typer.echo(f"OK: {out_path}")


__all__ = ["run"]
