"""CLI: tmax forecast (Phase 2 baseline)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import EmpiricalConditional, fit_empirical_conditional
from core.baselines.support import support_K
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.eval.intervals import discrete_ic
from core.features.builder import build_cp_features, build_panel
from core.ingest.iem_csv import load_observations
from core.io.logging import log_event, new_run_id
from core.io.timeutil import day_local_window
from core.labels.tmax import build_tmax_labels


def run(
    station_yaml: Path = typer.Option(Path("nzwn/config/station.yaml"), "--station-config"),
    csv: Path = typer.Option(Path("NZWN.csv"), "--csv"),
    target_date: str = typer.Option(..., "--date"),
    cp: str = typer.Option(..., "--cp"),
    train_start: str = typer.Option("2020-01-01", "--train-start"),
    train_end: str | None = typer.Option(None, "--train-end"),
    out_root: Path = typer.Option(Path("artifacts/forecasts"), "--out-root"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Emit a baseline forecast row with empirical-conditional prob_dist."""
    rid = new_run_id()
    cfg = load_station_config(station_yaml)
    cp_hhmm = f"{int(cp):02d}:00"
    if cp_hhmm not in cfg.cp_set_utc:
        raise typer.BadParameter(f"CP {cp_hhmm} not in CP_SET {cfg.cp_set_utc}")
    d = date.fromisoformat(target_date)
    train_end_d = date.fromisoformat(train_end) if train_end else date.fromordinal(d.toordinal() - 1)
    train_start_d = date.fromisoformat(train_start)

    obs, stats = load_observations(
        csv,
        tmp_min_c=cfg.tmp_c_int_plausibility.min,
        tmp_max_c=cfg.tmp_c_int_plausibility.max,
    )
    labels = build_tmax_labels(
        obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc
    )
    panel = build_panel(obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc)
    train_panel = panel.filter(
        (panel["date_local"] >= train_start_d) & (panel["date_local"] <= train_end_d)
    )
    climo = fit_climatology(labels, train_start=train_start_d, train_end=train_end_d)
    empirical = fit_empirical_conditional(
        train_panel, train_window=(train_start_d, train_end_d)
    )

    feats = build_cp_features(obs, date_local=d, cp_hhmm=cp_hhmm, tz_name=cfg.tz, labels=labels)
    p10, p90 = climo.percentiles_for(d)
    sk = support_K(
        p10, p90, tmp_min=cfg.tmp_c_int_plausibility.min, tmp_max=cfg.tmp_c_int_plausibility.max
    )
    kcp = feats.features.get("k_cp")
    if kcp is None:
        # fall back to climatology-only with no condition
        kcp_for_pred = Q(climo.tmax_dec_for(d))
    else:
        kcp_for_pred = int(kcp)
    prob_dist, source = empirical.predict_dist(
        month=d.month, cp=cp_hhmm, k_cp=kcp_for_pred, support_k=sk
    )
    p50 = max(prob_dist.items(), key=lambda kv: kv[1])[0]
    low, high = discrete_ic(prob_dist, p_low=0.10, p_high=0.90)
    forecast_row = {
        "run_id": rid,
        "date_local": d.isoformat(),
        "cp_utc": feats.cp_utc.isoformat(),
        "cp_local": feats.cp_local.isoformat(),
        "tz_name": cfg.tz,
        "station": cfg.icao,
        "p50_int": int(p50),
        "ic80_low_int": int(low),
        "ic80_high_int": int(high),
        "support_k": sk,
        "prob_dist": {str(k): v for k, v in prob_dist.items()},
        "prob_dist_source": source,
        "model_version": "baseline-empirical-v0.1",
        "tau": None,
        "fallback_rate": stats.fallback_rate,
    }

    log_event(
        "forecast",
        "forecast.emit",
        cp_utc=feats.cp_utc,
        cp_local=feats.cp_local,
        tz_name=cfg.tz,
        extra={
            "p50_int": forecast_row["p50_int"],
            "support_k_n": len(sk),
            "prob_dist_source": source,
        },
    )

    if dry_run:
        typer.echo(json.dumps(forecast_row, indent=2))
        return

    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / f"{rid}.json"
    with open(out_path, "w", encoding="ascii") as fh:
        json.dump(forecast_row, fh, ensure_ascii=True, sort_keys=True, indent=2)
    typer.echo(f"OK: {out_path}")


__all__ = ["run"]
