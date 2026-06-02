"""CLI smoke: ``forecast --model auto --dry-run`` returns valid JSON (Phase 3, T-11-9).

Proves the conservative router is wired into the CLI end-to-end:
  * Phase 3 has no live NWP, so the router degrades to ridge (or the empirical
    floor when training rows are insufficient) without exploding.
  * stdout stays pure JSON; the --model auto diagnostic goes to stderr.
  * the emitted row carries a ``routing`` block with ``spread_used == False``.

Heavy loaders are monkeypatched in the ``core.cli.forecast`` namespace (mirrors
tests/unit/test_cli_decide.py) so the 20 MB NZWN.csv and model fitting are avoided.
"""

from __future__ import annotations

import json
import types
from datetime import date, datetime, timezone

import pytest

from core.features.training_panel import FEATURE_COLUMNS


class _FakeDateCol:
    """Stand-in for a polars date Series used only for window filtering."""

    def __init__(self, dates):
        self._dates = dates

    def unique(self):
        return self

    def to_list(self):
        return list(self._dates)

    def __ge__(self, other):
        return True

    def __le__(self, other):
        return True


class _FakePanel:
    def __init__(self, dates):
        self._dates = dates

    def filter(self, *a, **kw):
        return self

    def __getitem__(self, key):
        return _FakeDateCol(self._dates)


class _FakeSeries:
    def __init__(self, height, dates):
        self._height = height
        self._dates = dates

    def to_numpy(self):
        import numpy as np

        return np.zeros(self._height)

    def to_list(self):
        return list(self._dates)[: self._height] or list(self._dates)


class _FakeTPanel:
    """Training panel whose only meaningful property is ``height``.

    When ``height >= 100`` the ridge branch fits (mocked); below that the auto
    path degrades to empirical and the column accessors are never touched.
    """

    def __init__(self, height, dates):
        self._height = height
        self._dates = [date(2025, 7, 1)] * height if height else list(dates)

    @property
    def height(self):
        return self._height

    def filter(self, *a, **kw):
        return self

    def __getitem__(self, key):
        return _FakeSeries(self._height, self._dates)


class _FakeClimo:
    def percentiles_for(self, d):
        return (10.0, 20.0)

    def tmax_dec_for(self, d):
        return 14.0


class _FakeEmpirical:
    def predict_dist(self, **kwargs):
        return {14: 1.0}, "empirical_fake"


class _FakeCfg:
    cp_set_utc = ["20:00", "21:00", "22:00", "23:00"]
    tz = "Pacific/Auckland"
    icao = "NZWN"

    class tmp_c_int_plausibility:
        min = -10
        max = 45


class _FakeStats:
    fallback_rate = 0.0


class _FakeFeats:
    cp_utc = datetime(2025, 7, 15, 10, 0, tzinfo=timezone.utc)
    cp_local = datetime(2025, 7, 15, 22, 0)
    features = {**{c: 1.0 for c in FEATURE_COLUMNS}, "k_cp": 14}


def _invoke_auto(monkeypatch, tpanel_height):
    """Monkeypatch the forecast pipeline and invoke ``--model auto --dry-run``.

    The router itself (recommend_route/resolve_servable) is NOT mocked -- that is
    the unit under test. With ecmwf/gfs unavailable it routes to ridge; the
    ridge fit is mocked, and ``tpanel_height`` decides ridge-served vs empirical.
    """
    dates = [date(2025, 7, 1), date(2025, 7, 2), date(2025, 7, 3)]

    monkeypatch.setattr("core.cli.forecast.load_station_config", lambda _: _FakeCfg())
    monkeypatch.setattr("core.cli.forecast.load_observations", lambda *a, **kw: (None, _FakeStats()))
    monkeypatch.setattr("core.cli.forecast.build_tmax_labels", lambda *a, **kw: None)
    monkeypatch.setattr("core.cli.forecast.build_panel", lambda *a, **kw: _FakePanel(dates))
    monkeypatch.setattr("core.cli.forecast.fit_climatology", lambda *a, **kw: _FakeClimo())
    monkeypatch.setattr("core.cli.forecast.fit_empirical_conditional", lambda *a, **kw: _FakeEmpirical())
    monkeypatch.setattr("core.cli.forecast.build_cp_features", lambda *a, **kw: _FakeFeats())
    monkeypatch.setattr("core.cli.forecast.support_K", lambda *a, **kw: [13, 14, 15, 16])
    monkeypatch.setattr("core.cli.forecast.log_event", lambda *a, **kw: None)
    monkeypatch.setattr(
        "core.cli.forecast.build_training_panel",
        lambda *a, **kw: _FakeTPanel(tpanel_height, dates),
    )
    monkeypatch.setattr(
        "core.cli.forecast.fit_ridge_band",
        lambda *a, **kw: types.SimpleNamespace(alpha=1.0),
    )
    monkeypatch.setattr("core.cli.forecast.ridge_predict_dist", lambda *a, **kw: [{14: 1.0}])

    from core.cli.forecast import run
    from typer.testing import CliRunner
    import typer

    app = typer.Typer()
    app.command()(run)
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        app,
        ["--date", "2025-07-15", "--cp", "22", "--model", "auto", "--dry-run"],
    )
    return result


def test_auto_dry_run_emits_valid_json_ridge_served(monkeypatch):
    """Enough training rows -> ridge is served; stdout is valid JSON with a routing block."""
    result = _invoke_auto(monkeypatch, tpanel_height=120)
    assert result.exit_code == 0, (result.stdout, result.stderr, repr(result.exception))

    row = json.loads(result.stdout)
    assert row["model_requested"] == "auto"
    assert row["served_model"] == "ridge"

    routing = row["routing"]
    assert routing["cp"] == 22
    assert routing["model_route"] == "ridge"          # no NWP in Phase 3 -> ridge
    assert routing["served_model"] == "ridge"
    assert routing["fallback_used"] is True           # routed to ridge by NWP-absent fallback
    assert routing["fallback_reason"] == "no_causal_nwp_fallback_ridge"
    assert routing["decision_reason"] is None          # a fallback, not a CP23-style conservative decision
    assert routing["degraded_reason"] is None         # ridge is servable, no further degrade
    assert routing["ecmwf_available"] is False
    assert routing["gfs_available"] is False
    assert routing["spread_used"] is False            # invariant: spread never routes

    # Banner is on stderr, never on stdout (keeps the JSON clean).
    assert "[forecast --model auto]" in result.stderr
    assert "spread_used=False" in result.stderr
    assert "[forecast --model auto]" not in result.stdout


def test_auto_dry_run_degrades_to_empirical_without_exploding(monkeypatch):
    """Too few training rows -> auto degrades to the empirical floor (does NOT raise)."""
    result = _invoke_auto(monkeypatch, tpanel_height=5)
    assert result.exit_code == 0, (result.stdout, result.stderr, repr(result.exception))

    row = json.loads(result.stdout)
    assert row["model_requested"] == "auto"
    assert row["served_model"] == "empirical"

    routing = row["routing"]
    assert routing["model_route"] == "ridge"
    assert routing["served_model"] == "empirical"
    assert routing["spread_used"] is False
    # The degradation reason records the row shortfall and the empirical fallback.
    assert "ridge_insufficient_rows_5" in routing["degraded_reason"]
    assert "fallback_empirical" in routing["degraded_reason"]
