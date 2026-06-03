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
from core.decision.sizing import size_side
from core.features.builder import build_cp_features, build_panel
from core.ingest.iem_csv import load_observations
from core.ingest.odds import event_url, snapshot_live
from core.io.logging import log_event, new_run_id
from core.labels.tmax import build_tmax_labels
from core.ops.schemas import ShadowSchemaError, validate_record


class ForecastChainError(Exception):
    """Raised when forecast-decision chain validation fails."""


def _load_forecast_json(
    forecast_path: Path,
    *,
    expected_date: str | None = None,
    expected_cp: str | None = None,
) -> tuple[dict, dict]:
    """Load and validate a forecast JSON file for the decision chain.

    Args:
        forecast_path: Path to forecast JSON file.
        expected_date: If provided, verify forecast date_local matches.
        expected_cp: If provided (e.g. "20"), verify forecast cp_utc hour matches.

    Returns:
        Tuple of (prob_dist dict, metadata dict with run_id, model_version).

    Raises:
        ForecastChainError: If file missing, validation fails, or date/CP mismatch.
    """
    if not forecast_path.exists():
        raise ForecastChainError(f"Forecast file not found: {forecast_path}")

    with open(forecast_path, "r", encoding="ascii") as fh:
        raw = json.load(fh)

    try:
        record = validate_record(raw)
    except ShadowSchemaError as exc:
        raise ForecastChainError(f"Forecast validation failed: {exc}") from exc

    # Cross-validate date_local.
    if expected_date is not None and record.date_local != expected_date:
        raise ForecastChainError(
            f"Forecast date mismatch: file has {record.date_local}, "
            f"expected {expected_date}"
        )

    # Cross-validate cp_utc hour.
    if expected_cp is not None:
        cp_utc_str = record.cp_utc
        cp_hour_in_file: str | None = None
        if "T" in cp_utc_str:
            try:
                cp_hour_in_file = cp_utc_str.split("T")[1].split(":")[0]
            except (IndexError, ValueError):
                pass
        expected_cp_padded = f"{int(expected_cp):02d}"
        if cp_hour_in_file is not None and cp_hour_in_file != expected_cp_padded:
            raise ForecastChainError(
                f"Forecast CP mismatch: file has CP{cp_hour_in_file}, "
                f"expected CP{expected_cp_padded}"
            )

    # Convert string keys back to int for prob_dist.
    prob_dist = {int(k): v for k, v in record.prob_dist.items()}

    metadata = {
        "forecast_run_id": record.run_id,
        "forecast_model_version": record.model_version,
        "forecast_file": str(forecast_path),
        "prob_dist_source": raw.get("prob_dist_source", "shadow_forecast_json"),
    }

    return prob_dist, metadata


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
    forecast_json: Path | None = typer.Option(
        None, "--forecast-json",
        help="Path to a forecast JSON file. If provided, uses its prob_dist instead of computing internally.",
    ),
) -> None:
    """Emit a live decision row: forecast + odds + sizing.

    When --forecast-json is provided, the decision consumes the probability
    distribution from that file directly (no internal forecast reconstruction).
    This creates an auditable chain: forecast file -> decision.
    """
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
    if labels is not None:
        train_dates = [
            d_val for d_val in labels["date_local"].unique().to_list()
            if d_val is not None and train_start_d <= d_val <= train_end_d
        ]
    else:
        train_dates = None
    panel = build_panel(obs, labels, tz_name=cfg.tz, cp_set=cfg.cp_set_utc, dates=train_dates)
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

    # Forecast chain: either load from file or compute internally.
    forecast_linkage: dict | None = None
    if forecast_json is not None:
        # Load prob_dist from external forecast file (no implicit fallback).
        # Cross-validate that the forecast matches the requested date and CP.
        prob_dist, forecast_linkage = _load_forecast_json(
            forecast_json,
            expected_date=target_date,
            expected_cp=cp,
        )
        source = forecast_linkage["prob_dist_source"]
        typer.echo(
            f"[decide --forecast-json] Using prob_dist from {forecast_json.name} "
            f"(run_id={forecast_linkage['forecast_run_id']})",
            err=True,
        )
    else:
        # Compute internally (original behavior).
        kcp = feats.features.get("k_cp")
        kcp_for_pred = int(kcp) if kcp is not None else Q(climo.tmax_dec_for(d))
        prob_dist, source = empirical.predict_dist(
            month=d.month, cp=cp_hhmm, k_cp=kcp_for_pred, support_k=sk
        )
        forecast_linkage = None

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
    except (ConnectionError, TimeoutError, ValueError, KeyError, OSError) as exc:
        # Live odds genuinely unavailable (network / parsing). Bugs in decide()/size_side()
        # below must NOT be masked here -> they run in the else block and are allowed to raise.
        odds_status = "unavailable"
        notes.append(f"odds_unavailable:{type(exc).__name__}")
    else:
        odds_sha256 = snap.sha256
        exec_contract = default_execution_contract()
        thresholds = Thresholds()
        forecast_row = ForecastRow(
            prob_dist=prob_dist,
            confidence_score=confidence_score,
            spike_risk=spike_risk,
        )
        # Map an engine trade state to the side to size (None = no position).
        trade_side = {"OPPORTUNITY_ASSYMETRIC": "BUY_YES", "BUY_NO": "BUY_NO"}
        for b in snap.brackets:
            py = p_yes(prob_dist, b.contract)
            row = {
                "label": b.label,
                "contract": {"k_lo": b.contract.k_lo, "k_hi": b.contract.k_hi},
                "p_yes": round(py, 6),
                "price_yes": b.price_yes,
                "price_no": b.price_no,
            }
            # Degenerate price (resolved market / no live quote): never size a boundary price.
            if not (0.0 < b.price_yes < 1.0 and 0.0 < b.price_no < 1.0):
                row.update(decide_state="NO_TRADE_RESOLVED", side=None,
                           ev=None, kelly_fraction=None, stake=0.0)
                bracket_rows.append(row)
                continue
            dec = decide(forecast_row, b.contract, b.price_yes, b.price_no, thresholds)
            # EV/Kelly/stake follow the ENGINE's chosen side (single source of truth); 0 otherwise.
            # size_side takes p_yes and converts to (1-p_yes) for BUY_NO internally.
            side = trade_side.get(dec.state)
            sr = size_side(side, py, b.price_yes if side == "BUY_YES" else b.price_no,
                           contract=exec_contract) if side else None
            row.update(
                decide_state=dec.state,
                side=side,
                ev=round(sr.expected_value, 6) if sr else None,
                kelly_fraction=round(sr.kelly_fraction, 6) if sr else None,
                stake=round(sr.stake, 6) if sr else 0.0,
            )
            bracket_rows.append(row)

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

    # Add forecast linkage if loaded from external file.
    if forecast_linkage is not None:
        decision_row["forecast_run_id"] = forecast_linkage["forecast_run_id"]
        decision_row["forecast_model_version"] = forecast_linkage["forecast_model_version"]
        decision_row["forecast_file"] = forecast_linkage["forecast_file"]

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


__all__ = ["run", "ForecastChainError", "_load_forecast_json"]
