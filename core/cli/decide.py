"""CLI: live decision (Phase 8 plumbing)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from core.baselines.climatology import fit_climatology
from core.baselines.empirical import fit_empirical_conditional
from core.baselines.support import support_K
from core.contracts.execution import EXECUTION_VERSION, default_execution_contract
from core.contracts.quantization import Q
from core.contracts.station import load_station_config
from core.decision.engine import ForecastRow, Thresholds, decide
from core.decision.market_map import p_yes
from core.decision.sizing import size_book
from core.features.builder import build_cp_features, build_panel
from core.ingest.iem_csv import load_observations
from core.ingest.odds import event_url, snapshot_live
from core.io.logging import log_event, new_run_id
from core.labels.tmax import build_tmax_labels


def run(
    station_yaml: Path = typer.Option(Path("nzwn/config/station.yaml"), "--station-config"),
    csv: Path = typer.Option(Path("NZWN.csv"), "--csv"),
    target_date: str = typer.Option(..., "--date"),
    cp: str = typer.Option(..., "--cp"),
    city: str = typer.Option("Wellington", "--city"),
    train_start: str = typer.Option("2020-01-01", "--train-start"),
    train_end: str | None = typer.Option(None, "--train-end"),
    out_root: Path = typer.Option(Path("artifacts/decisions"), "--out-root"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Emit a live decision row: forecast + odds + sizing."""
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
    labels = build_tmax_labels(obs, tz_name=cfg.tz, cp_set_utc=cfg.cp_set_utc)
    panel = build_panel(obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc)
    train_panel = panel.filter(
        (panel["date_local"] >= train_start_d) & (panel["date_local"] <= train_end_d)
    )
    climo = fit_climatology(labels, train_start=train_start_d, train_end=train_end_d)
    empirical = fit_empirical_conditional(train_panel, train_window=(train_start_d, train_end_d))

    feats = build_cp_features(obs, date_local=d, cp_hhmm=cp_hhmm, tz_name=cfg.tz, labels=labels)
    p10, p90 = climo.percentiles_for(d)
    sk = support_K(
        p10, p90, tmp_min=cfg.tmp_c_int_plausibility.min, tmp_max=cfg.tmp_c_int_plausibility.max
    )
    kcp = feats.features.get("k_cp")
    kcp_for_pred = int(kcp) if kcp is not None else Q(climo.tmax_dec_for(d))
    prob_dist, source = empirical.predict_dist(
        month=d.month, cp=cp_hhmm, k_cp=kcp_for_pred, support_k=sk
    )

    # Phase 5 confidence not ready; set 1.0 so gate never blocks.
    confidence_score = 1.0
    spike_risk = 0.0
    notes = [
        "confidence_uncalibrated_phase5_not_ready",
        "spike_risk_zero_phase7_not_ready",
    ]

    cp_utc = feats.cp_utc
    ev_url = event_url(city, d)

    # Fetch live odds
    odds_status = "ok"
    odds_sha256: str | None = None
    bracket_rows: list[dict] = []
    try:
        snap = snapshot_live(city, d, cp_utc)
        odds_sha256 = snap.sha256
        exec_contract = default_execution_contract()
        book_map = {label: sr for label, sr in size_book(prob_dist, snap.brackets, contract=exec_contract)}
        thresholds = Thresholds()
        forecast_row = ForecastRow(
            prob_dist=prob_dist,
            confidence_score=confidence_score,
            spike_risk=spike_risk,
        )
        for b in snap.brackets:
            py = p_yes(prob_dist, b.contract)
            dec = decide(forecast_row, b.contract, b.price_yes, b.price_no, thresholds)
            sr = book_map.get(b.label)
            bracket_rows.append({
                "label": b.label,
                "contract": {"k_lo": b.contract.k_lo, "k_hi": b.contract.k_hi},
                "p_yes": round(py, 6),
                "price_yes": b.price_yes,
                "price_no": b.price_no,
                "decide_state": dec.state,
                "ev": round(sr.expected_value, 6) if sr else None,
                "kelly_fraction": round(sr.kelly_fraction, 6) if sr else None,
                "stake": round(sr.stake, 6) if sr else 0.0,
            })
    except Exception:
        odds_status = "unavailable"

    decision_row = {
        "run_id": rid,
        "date_local": d.isoformat(),
        "cp_utc": cp_utc.isoformat(),
        "city": city,
        "event_url": ev_url,
        "execution_version": EXECUTION_VERSION,
        "prob_dist": {str(k): v for k, v in prob_dist.items()},
        "brackets": bracket_rows,
        "odds_status": odds_status,
        "odds_sha256": odds_sha256,
        "notes": notes,
    }

    log_event(
        "decision",
        "decision.emit",
        cp_utc=cp_utc,
        cp_local=feats.cp_local,
        tz_name=cfg.tz,
        extra={"odds_status": odds_status, "n_brackets": len(bracket_rows)},
    )

    if dry_run:
        typer.echo(json.dumps(decision_row, indent=2, ensure_ascii=True))
        return

    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / f"{rid}.json"
    with open(out_path, "w", encoding="ascii") as fh:
        json.dump(decision_row, fh, ensure_ascii=True, sort_keys=True, indent=2)
    typer.echo(f"OK: {out_path}")


__all__ = ["run"]
