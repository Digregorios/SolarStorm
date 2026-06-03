"""Unit tests for forecast-decision chain (Phase 5.1, Agent B).

Tests cover:
- Decision uses forecast prob_dist exactly (no reconstruction)
- Odds unavailable still emits auditable artifact
- No implicit empirical fallback when forecast file is missing/invalid
- Linkage fields (forecast_run_id, forecast_model_version, forecast_file) are mandatory
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.cli.decide import ForecastChainError, _load_forecast_json
from core.ops.schemas import REQUIRED_FORECAST_FIELDS


# --- Fixture helpers ----------------------------------------------------------


def _write_valid_forecast(path: Path, **overrides) -> Path:
    """Write a valid forecast JSON file for testing."""
    record = {
        "run_id": "forecast-chain-test-123",
        "date_local": "2025-01-15",
        "cp_utc": "2025-01-15T20:00:00+00:00",
        "prob_dist": {"17": 0.1, "18": 0.3, "19": 0.4, "20": 0.15, "21": 0.05},
        "model_version": "phase3-ridge-band-v1.0",
        "routing": {
            "model_route": "ecmwf",
            "served_model": "ridge",
            "fallback_used": False,
        },
        "p50_int": 19,
        "ic80_low_int": 17,
        "ic80_high_int": 21,
        "prob_dist_source": "ridge_band_alpha_0.5",
    }
    record.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii") as fh:
        json.dump(record, fh)
    return path


# --- _load_forecast_json tests ------------------------------------------------


def test_load_forecast_json_success(tmp_path: Path):
    forecast_path = _write_valid_forecast(tmp_path / "forecast.json")
    prob_dist, metadata = _load_forecast_json(forecast_path)

    # prob_dist keys should be converted to int.
    assert all(isinstance(k, int) for k in prob_dist.keys())
    assert prob_dist[19] == 0.4
    assert prob_dist[18] == 0.3

    # Metadata should contain linkage fields.
    assert metadata["forecast_run_id"] == "forecast-chain-test-123"
    assert metadata["forecast_model_version"] == "phase3-ridge-band-v1.0"
    assert metadata["forecast_file"] == str(forecast_path)
    assert metadata["prob_dist_source"] == "ridge_band_alpha_0.5"


def test_load_forecast_json_missing_file(tmp_path: Path):
    missing_path = tmp_path / "does_not_exist.json"
    with pytest.raises(ForecastChainError, match="Forecast file not found"):
        _load_forecast_json(missing_path)


def test_load_forecast_json_missing_required_field(tmp_path: Path):
    forecast_path = tmp_path / "invalid.json"
    incomplete = {
        "run_id": "x",
        "date_local": "2025-01-15",
        # Missing: cp_utc, prob_dist, model_version, routing
    }
    with open(forecast_path, "w") as fh:
        json.dump(incomplete, fh)

    with pytest.raises(ForecastChainError, match="Forecast validation failed"):
        _load_forecast_json(forecast_path)


def test_load_forecast_json_invalid_prob_dist(tmp_path: Path):
    forecast_path = _write_valid_forecast(
        tmp_path / "forecast.json",
        prob_dist="not a dict",  # Override with invalid type
    )

    with pytest.raises(ForecastChainError, match="prob_dist must be a dict"):
        _load_forecast_json(forecast_path)


# --- prob_dist exactness test -------------------------------------------------


def test_prob_dist_preserved_exactly(tmp_path: Path):
    """Decision must use the exact prob_dist from the forecast file."""
    # Create a forecast with a specific prob_dist.
    specific_dist = {"15": 0.05, "16": 0.15, "17": 0.30, "18": 0.35, "19": 0.10, "20": 0.05}
    forecast_path = _write_valid_forecast(
        tmp_path / "forecast.json",
        prob_dist=specific_dist,
    )

    prob_dist, _ = _load_forecast_json(forecast_path)

    # Verify prob_dist matches exactly (keys as int, values preserved).
    expected = {int(k): v for k, v in specific_dist.items()}
    assert prob_dist == expected

    # Verify no rounding or transformation occurred.
    for k, v in specific_dist.items():
        assert prob_dist[int(k)] == v


# --- Linkage fields mandatory tests -------------------------------------------


def test_linkage_fields_present(tmp_path: Path):
    """When --forecast-json is used, linkage fields must be in metadata."""
    forecast_path = _write_valid_forecast(tmp_path / "forecast.json")
    _, metadata = _load_forecast_json(forecast_path)

    # All linkage fields must be present.
    assert "forecast_run_id" in metadata
    assert "forecast_model_version" in metadata
    assert "forecast_file" in metadata

    # Values must be non-empty.
    assert metadata["forecast_run_id"]
    assert metadata["forecast_model_version"]
    assert metadata["forecast_file"]


def test_linkage_fields_propagate_run_id(tmp_path: Path):
    """The decision's forecast_run_id must match the forecast's run_id."""
    custom_run_id = "unique-forecast-id-abc123"
    forecast_path = _write_valid_forecast(
        tmp_path / "forecast.json",
        run_id=custom_run_id,
    )

    _, metadata = _load_forecast_json(forecast_path)
    assert metadata["forecast_run_id"] == custom_run_id


# --- No implicit fallback tests -----------------------------------------------


def test_no_implicit_fallback_on_missing_file(tmp_path: Path):
    """When forecast file is missing, must error - not fall back to empirical."""
    with pytest.raises(ForecastChainError, match="not found"):
        _load_forecast_json(tmp_path / "missing.json")


def test_no_implicit_fallback_on_invalid_schema(tmp_path: Path):
    """When forecast file has invalid schema, must error - not fall back."""
    forecast_path = tmp_path / "bad.json"
    with open(forecast_path, "w") as fh:
        json.dump({"incomplete": "data"}, fh)

    with pytest.raises(ForecastChainError, match="validation failed"):
        _load_forecast_json(forecast_path)


# --- ForecastChainError tests -------------------------------------------------


def test_forecast_chain_error_is_exception():
    """ForecastChainError should be a proper Exception subclass."""
    assert issubclass(ForecastChainError, Exception)
    err = ForecastChainError("test message")
    assert str(err) == "test message"


# --- Odds unavailable still auditable -----------------------------------------


def test_odds_unavailable_linkage_still_present(tmp_path: Path):
    """Even when odds are unavailable, forecast linkage fields should be loadable.

    Note: This tests the loading function, not the full decide flow.
    The full decide flow with --forecast-json and odds unavailable is
    tested in integration tests.
    """
    forecast_path = _write_valid_forecast(tmp_path / "forecast.json")
    prob_dist, metadata = _load_forecast_json(forecast_path)

    # Linkage should work regardless of odds availability.
    assert metadata["forecast_run_id"] is not None
    assert prob_dist is not None


# --- Cross-validation tests (date/CP mismatch) --------------------------------


def test_cross_validate_date_mismatch(tmp_path: Path):
    """Forecast for 2025-01-15 loaded with --date 2025-01-16 must error."""
    forecast_path = _write_valid_forecast(
        tmp_path / "forecast.json",
        date_local="2025-01-15",
    )
    with pytest.raises(ForecastChainError, match="date mismatch"):
        _load_forecast_json(forecast_path, expected_date="2025-01-16")


def test_cross_validate_date_match(tmp_path: Path):
    """Forecast date matches expected -> no error."""
    forecast_path = _write_valid_forecast(
        tmp_path / "forecast.json",
        date_local="2025-01-15",
    )
    prob_dist, _ = _load_forecast_json(forecast_path, expected_date="2025-01-15")
    assert prob_dist is not None


def test_cross_validate_cp_mismatch(tmp_path: Path):
    """Forecast for CP20 loaded with --cp 22 must error."""
    forecast_path = _write_valid_forecast(
        tmp_path / "forecast.json",
        cp_utc="2025-01-15T20:00:00+00:00",
    )
    with pytest.raises(ForecastChainError, match="CP mismatch"):
        _load_forecast_json(forecast_path, expected_cp="22")


def test_cross_validate_cp_match(tmp_path: Path):
    """Forecast CP matches expected -> no error."""
    forecast_path = _write_valid_forecast(
        tmp_path / "forecast.json",
        cp_utc="2025-01-15T20:00:00+00:00",
    )
    prob_dist, _ = _load_forecast_json(forecast_path, expected_cp="20")
    assert prob_dist is not None


def test_cross_validate_both_mismatch(tmp_path: Path):
    """Both date and CP wrong -> date mismatch raised first."""
    forecast_path = _write_valid_forecast(
        tmp_path / "forecast.json",
        date_local="2025-01-15",
        cp_utc="2025-01-15T20:00:00+00:00",
    )
    with pytest.raises(ForecastChainError, match="date mismatch"):
        _load_forecast_json(
            forecast_path,
            expected_date="2025-06-01",
            expected_cp="23",
        )
