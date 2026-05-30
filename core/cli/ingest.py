"""CLI: ingest-history + build-features."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer

from core.contracts.station import load_station_config
from core.features.builder import build_cp_features
from core.ingest.iem_csv import load_observations
from core.ingest.metar_live import fetch_observations, merge_observations
from core.ingest.snapshot import snapshot_csv_by_local_day
from core.io.hashing import sha256_file
from core.io.logging import log_event, new_run_id


def ingest_history(
    csv: Path = typer.Option(..., "--csv", help="Path to NZWN.csv (IEM ASOS)."),
    station_yaml: Path = typer.Option(
        Path("nzwn/config/station.yaml"), "--station-config", help="Station YAML"
    ),
    out_root: Path = typer.Option(
        Path("artifacts/raw/metar"), "--out-root", help="Snapshot root."
    ),
) -> None:
    """Snapshot raw METAR by local day with SHA256 manifest (REQ-DAT-1)."""
    new_run_id()
    cfg = load_station_config(station_yaml)
    log_event("ingest", "ingest.start", extra={"csv": str(csv), "station": cfg.icao})
    obs, stats = load_observations(
        csv,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    src_sha = sha256_file(csv)
    hashes = snapshot_csv_by_local_day(
        obs, station=cfg.icao, tz_name=cfg.tz, out_root=out_root, source_csv_sha256=src_sha
    )
    log_event(
        "ingest",
        "ingest.done",
        extra={
            "n_rows": obs.height,
            "n_dates": len(hashes),
            "parse_stats": stats.to_dict(),
            "source_sha256": src_sha,
        },
    )
    typer.echo(f"OK: {obs.height} rows, {len(hashes)} dates, fallback_rate={stats.fallback_rate:.5f}")


def build_features(
    station_yaml: Path = typer.Option(Path("nzwn/config/station.yaml"), "--station-config"),
    target_date: str = typer.Option(..., "--date", help="Local date YYYY-MM-DD"),
    cp: str = typer.Option(..., "--cp", help="CP HH (integer hour, REQ-CON-6)"),
    csv: Path = typer.Option(Path("NZWN.csv"), "--csv"),
) -> None:
    """Build the per-CP feature row for one date."""
    new_run_id()
    cfg = load_station_config(station_yaml)
    cp_hhmm = f"{int(cp):02d}:00"
    if cp_hhmm not in cfg.cp_set_utc:
        raise typer.BadParameter(f"CP {cp_hhmm} not in CP_SET {cfg.cp_set_utc} (REQ-CON-6).")
    d = date.fromisoformat(target_date)
    obs, _ = load_observations(
        csv,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    # REQ-DAT-2 + design 4.5: D-1 features need the label panel.
    from core.labels.tmax import build_tmax_labels

    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    feats = build_cp_features(
        obs, date_local=d, cp_hhmm=cp_hhmm, tz_name=cfg.tz, labels=labels
    )
    log_event(
        "features",
        "features.built",
        cp_utc=feats.cp_utc,
        cp_local=feats.cp_local,
        tz_name=cfg.tz,
        extra={
            "date_local": d.isoformat(),
            "feature_max_ts": feats.feature_max_ts_utc.isoformat(),
            "tmax_d_minus_1_int": feats.features.get("tmax_d_minus_1_int"),
        },
    )
    typer.echo(
        f"OK: cp_utc={feats.cp_utc.isoformat()} "
        f"feature_max_ts={feats.feature_max_ts_utc.isoformat()} "
        f"tmax_d_minus_1_int={feats.features.get('tmax_d_minus_1_int')}"
    )


def ingest_live(
    station_yaml: Path = typer.Option(Path("nzwn/config/station.yaml"), "--station-config"),
    csv: Path = typer.Option(Path("NZWN.csv"), "--csv", help="Historical IEM CSV to merge with."),
    hours: int = typer.Option(96, "--hours", help="Lookback window of live METAR."),
    out_csv: Path | None = typer.Option(None, "--out-csv", help="Optional merged CSV path."),
) -> None:
    """Fetch CURRENT METAR (aviationweather.gov) and merge with history (REQ-DAT-1).

    Live obs share the historical schema (one source of truth for the integer temperature),
    so the label/feature/forecast path runs on fresh data unchanged. With ``--out-csv`` the
    merged ``valid,metar`` frame is written for downstream reuse; otherwise it just reports
    coverage so an operator/cron can confirm the 30-min feed is current.
    """
    new_run_id()
    cfg = load_station_config(station_yaml)
    tmin, tmax = cfg.tmp_c_int_plausibility.min, cfg.tmp_c_int_plausibility.max
    live, stats = fetch_observations(cfg.icao, hours=hours, tmp_min_c=tmin, tmp_max_c=tmax)
    n_hist = 0
    if csv.exists():
        hist, _ = load_observations(csv, tmp_min_c=tmin, tmp_max_c=tmax)
        n_hist = hist.height
        merged = merge_observations(hist, live)
    else:
        merged = live.sort("ts_utc")
    log_event("ingest", "ingest.live", extra={
        "station": cfg.icao, "n_live": live.height, "n_hist": n_hist,
        "n_merged": merged.height, "parse_stats": stats.to_dict(),
    })
    if out_csv is not None:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        merged.select(["valid", "metar"] if "valid" in merged.columns else ["ts_utc", "metar"]).write_csv(out_csv)
    live_max = live["ts_utc"].max() if live.height else None
    typer.echo(
        f"OK: live={live.height} (ok={stats.n_parsed_ok}) hist={n_hist} merged={merged.height} "
        f"latest_live={live_max}"
    )


__all__ = ["ingest_history", "build_features", "ingest_live"]