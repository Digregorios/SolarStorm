"""Unit tests for core.cli.decide (Phase 8 plumbing)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from core.decision.market_map import ContractRange
from core.ingest.odds import OddsBracket, OddsSnapshot


def _fake_snapshot(city, d, cp_utc, **kwargs):
    """Return a minimal OddsSnapshot with two brackets."""
    return OddsSnapshot(
        slug="highest-temperature-in-wellington-on-july-15-2025",
        event_url="https://polymarket.com/event/highest-temperature-in-wellington-on-july-15-2025",
        cp_utc=cp_utc,
        ts_utc=datetime(2025, 7, 15, 3, 0, tzinfo=timezone.utc),
        sha256="abc123" * 8 + "abcdef12",
        brackets=(
            OddsBracket(
                contract=ContractRange(k_lo=14, k_hi=14),
                label="14",
                price_yes=0.30,
                price_no=0.70,
                best_ask=None,
            ),
            OddsBracket(
                contract=ContractRange(k_lo=15, k_hi=None),
                label="15 or higher",
                price_yes=0.20,
                price_no=0.80,
                best_ask=None,
            ),
        ),
    )


def _fake_run(tmp_path, monkeypatch, snapshot_fn):
    """Run decide.run with monkeypatched odds and minimal forecast pipeline."""
    # Monkeypatch snapshot_live at the module level where it is imported
    monkeypatch.setattr("core.cli.decide.snapshot_live", snapshot_fn)

    # Build a minimal prob_dist and monkeypatch the forecast pipeline
    prob_dist = {13: 0.1, 14: 0.5, 15: 0.3, 16: 0.1}

    class FakeFeats:
        cp_utc = datetime(2025, 7, 15, 3, 0, tzinfo=timezone.utc)
        cp_local = datetime(2025, 7, 15, 15, 0)
        features = {"k_cp": 14}

    class FakeClimo:
        def percentiles_for(self, d):
            return (10, 20)

        def tmax_dec_for(self, d):
            return 14.5

    class FakeEmpirical:
        def predict_dist(self, **kwargs):
            return prob_dist, "test_source"

    class FakeCfg:
        cp_set_utc = ["23:00"]
        tz = "Pacific/Auckland"
        icao = "NZWN"

        class tmp_c_int_plausibility:
            min = -10
            max = 45

    class FakeStats:
        fallback_rate = 0.0

    monkeypatch.setattr("core.cli.decide.load_station_config", lambda _: FakeCfg())
    monkeypatch.setattr("core.cli.decide.load_observations", lambda *a, **kw: (None, FakeStats()))
    monkeypatch.setattr("core.cli.decide.build_tmax_labels", lambda *a, **kw: None)
    class FakePanel:
        def filter(self, *a, **kw):
            return self
        def __getitem__(self, key):
            return self
        def __ge__(self, other):
            return True
        def __le__(self, other):
            return True
        def __and__(self, other):
            return True

    monkeypatch.setattr("core.cli.decide.build_panel", lambda *a, **kw: FakePanel())
    monkeypatch.setattr("core.cli.decide.fit_climatology", lambda *a, **kw: FakeClimo())
    monkeypatch.setattr("core.cli.decide.fit_empirical_conditional", lambda *a, **kw: FakeEmpirical())
    monkeypatch.setattr("core.cli.decide.build_cp_features", lambda *a, **kw: FakeFeats())
    monkeypatch.setattr("core.cli.decide.support_K", lambda *a, **kw: [13, 14, 15, 16])
    monkeypatch.setattr("core.cli.decide.log_event", lambda *a, **kw: None)

    from core.cli.decide import run
    from typer.testing import CliRunner
    import typer

    app = typer.Typer()
    app.command()(run)
    runner = CliRunner()
    out_dir = tmp_path / "decisions"
    result = runner.invoke(app, [
        "--date", "2025-07-15",
        "--cp", "23",
        "--city", "Wellington",
        "--out-root", str(out_dir),
    ])
    return result, out_dir


def test_decision_row_ok(tmp_path, monkeypatch):
    """Happy path: snapshot_live returns data -> decision row with expected keys."""
    result, out_dir = _fake_run(tmp_path, monkeypatch, _fake_snapshot)
    assert result.exit_code == 0, result.output
    files = list(out_dir.glob("*.json"))
    assert len(files) == 1
    row = json.loads(files[0].read_text(encoding="ascii"))
    # Required keys
    for key in (
        "run_id", "date_local", "cp_utc", "city", "event_url",
        "execution_version", "prob_dist", "brackets", "odds_status",
        "odds_sha256", "notes",
    ):
        assert key in row, f"missing key: {key}"
    assert row["odds_status"] == "ok"
    assert len(row["brackets"]) == 2
    # Per-bracket keys
    for b in row["brackets"]:
        for bk in ("label", "contract", "p_yes", "price_yes", "price_no",
                   "decide_state", "ev", "kelly_fraction", "stake"):
            assert bk in b, f"missing bracket key: {bk}"


def test_decision_row_unavailable(tmp_path, monkeypatch):
    """snapshot_live raises -> odds_status='unavailable', no crash."""
    def _raise(*a, **kw):
        raise ConnectionError("network down")

    result, out_dir = _fake_run(tmp_path, monkeypatch, _raise)
    assert result.exit_code == 0, result.output
    files = list(out_dir.glob("*.json"))
    assert len(files) == 1
    row = json.loads(files[0].read_text(encoding="ascii"))
    assert row["odds_status"] == "unavailable"
    assert row["brackets"] == []
    assert row["odds_sha256"] is None
