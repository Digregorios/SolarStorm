"""Unit tests for core/ops/shadow_runner.py (Phase 5.1).

Tests cover:
- Schema validation
- Atomic write behavior
- Idempotency (skip if exists)
- Synthetic runner (no network, using mocks)
- Fallback determinism
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.ops.schemas import (
    REQUIRED_FORECAST_FIELDS,
    ShadowForecastRecord,
    ShadowSchemaError,
    validate_record,
)
from core.ops.shadow_runner import (
    DEFAULT_CPS,
    ShadowRunner,
    ShadowRunnerConfig,
    ShadowRunnerError,
    _atomic_write,
    _output_path,
    _parse_forecast_output,
)


# --- Schema validation tests -------------------------------------------------


def _valid_record() -> dict:
    return {
        "run_id": "test-run-123",
        "date_local": "2025-01-15",
        "cp_utc": "2025-01-15T20:00:00+00:00",
        "prob_dist": {"18": 0.3, "19": 0.5, "20": 0.2},
        "model_version": "phase3-ridge-band-v1.0",
        "routing": {"model_route": "ecmwf", "served_model": "ridge"},
        "p50_int": 19,
        "ic80_low_int": 17,
        "ic80_high_int": 21,
    }


def test_validate_record_success():
    raw = _valid_record()
    record = validate_record(raw)
    assert record.run_id == "test-run-123"
    assert record.date_local == "2025-01-15"
    assert record.prob_dist["19"] == 0.5
    assert record.p50_int == 19


def test_validate_record_missing_field():
    raw = _valid_record()
    del raw["run_id"]
    with pytest.raises(ShadowSchemaError, match="Missing required fields"):
        validate_record(raw)


def test_validate_record_prob_dist_not_dict():
    raw = _valid_record()
    raw["prob_dist"] = "not a dict"
    with pytest.raises(ShadowSchemaError, match="prob_dist must be a dict"):
        validate_record(raw)


def test_validate_record_routing_not_dict():
    raw = _valid_record()
    raw["routing"] = None
    with pytest.raises(ShadowSchemaError, match="routing must be a dict"):
        validate_record(raw)


def test_shadow_forecast_record_to_dict():
    raw = _valid_record()
    record = ShadowForecastRecord.from_dict(raw)
    d = record.to_dict()
    assert d["run_id"] == raw["run_id"]
    assert d["prob_dist"] == raw["prob_dist"]


# --- Atomic write tests -------------------------------------------------------


def test_atomic_write_creates_file(tmp_path: Path):
    out = tmp_path / "test.jsonl"
    lines = ['{"a": 1}', '{"b": 2}']
    _atomic_write(out, lines)

    assert out.exists()
    content = out.read_text(encoding="ascii").strip().split("\n")
    assert content == lines
    assert not out.with_suffix(".tmp").exists()


def test_atomic_write_overwrites_existing(tmp_path: Path):
    out = tmp_path / "test.jsonl"
    out.write_text("old content\n")

    _atomic_write(out, ["new line"])
    assert out.read_text().strip() == "new line"


def test_atomic_write_creates_parent_dirs(tmp_path: Path):
    out = tmp_path / "nested" / "dir" / "test.jsonl"
    _atomic_write(out, ["data"])
    assert out.exists()


# --- Output path tests --------------------------------------------------------


def test_output_path_format():
    root = Path("/tmp/shadow")
    d = date(2025, 1, 15)
    p = _output_path(root, d)
    assert p == Path("/tmp/shadow/forecasts/2025-01-15.jsonl")


# --- Parse forecast output tests ---------------------------------------------


def test_parse_forecast_output_success():
    stdout = "Some preamble text\n" + json.dumps(_valid_record())
    result = _parse_forecast_output(stdout)
    assert result["run_id"] == "test-run-123"


def test_parse_forecast_output_no_json():
    with pytest.raises(ShadowRunnerError, match="No JSON found"):
        _parse_forecast_output("no json here")


# --- ShadowRunner tests (synthetic, no network) ------------------------------


def _mock_forecast_stdout(record: dict | None = None) -> str:
    """Generate mock stdout from `tmax forecast --dry-run`."""
    r = record or _valid_record()
    return f"[forecast --model auto] some banner\n{json.dumps(r)}"


def test_runner_run_date_success(tmp_path: Path):
    config = ShadowRunnerConfig(shadow_root=tmp_path, cps=(20, 21))

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_mock_forecast_stdout(),
            stderr="",
        )
        runner = ShadowRunner(config)
        result = runner.run_date(date(2025, 1, 15))

    assert result.n_success == 2
    assert result.n_failed == 0
    assert not result.skipped
    assert result.output_path is not None
    assert result.output_path.exists()

    # Verify JSONL content.
    lines = result.output_path.read_text().strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        record = json.loads(line)
        assert "run_id" in record


def test_runner_idempotent_skip(tmp_path: Path):
    config = ShadowRunnerConfig(shadow_root=tmp_path, cps=(20,), force=False)

    # Pre-create output file with a VALID record (not just any content).
    out_path = _output_path(tmp_path, date(2025, 1, 15))
    out_path.parent.mkdir(parents=True)
    valid = _valid_record()
    with open(out_path, "w") as fh:
        fh.write(json.dumps(valid) + "\n")

    runner = ShadowRunner(config)
    result = runner.run_date(date(2025, 1, 15))

    assert result.skipped
    assert result.n_success == 0


def test_runner_force_overwrites(tmp_path: Path):
    config = ShadowRunnerConfig(shadow_root=tmp_path, cps=(20,), force=True)

    # Pre-create output file.
    out_path = _output_path(tmp_path, date(2025, 1, 15))
    out_path.parent.mkdir(parents=True)
    out_path.write_text('{"old": true}\n')

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_mock_forecast_stdout(),
            stderr="",
        )
        runner = ShadowRunner(config)
        result = runner.run_date(date(2025, 1, 15))

    assert not result.skipped
    assert result.n_success == 1
    # File should be overwritten.
    assert '"old"' not in out_path.read_text()


def test_runner_handles_subprocess_failure(tmp_path: Path):
    config = ShadowRunnerConfig(shadow_root=tmp_path, cps=(20, 21))

    def side_effect(*args, **kwargs):
        cp = int(args[0][args[0].index("--cp") + 1])
        if cp == 20:
            return MagicMock(returncode=0, stdout=_mock_forecast_stdout(), stderr="")
        else:
            return MagicMock(returncode=1, stdout="", stderr="NWP unavailable")

    with patch("subprocess.run", side_effect=side_effect):
        runner = ShadowRunner(config)
        result = runner.run_date(date(2025, 1, 15))

    assert result.n_success == 1
    assert result.n_failed == 1
    assert any(cp == 21 for cp, _ in result.errors)


def test_runner_handles_timeout(tmp_path: Path):
    config = ShadowRunnerConfig(shadow_root=tmp_path, cps=(20,), timeout_s=1)

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 1)):
        runner = ShadowRunner(config)
        result = runner.run_date(date(2025, 1, 15))

    assert result.n_success == 0
    assert result.n_failed == 1
    assert "TimeoutExpired" in result.errors[0][1]


def test_runner_run_range(tmp_path: Path):
    config = ShadowRunnerConfig(shadow_root=tmp_path, cps=(20,))

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_mock_forecast_stdout(),
            stderr="",
        )
        runner = ShadowRunner(config)
        results = runner.run_range(date(2025, 1, 1), date(2025, 1, 3))

    assert len(results) == 3
    assert all(r.n_success == 1 for r in results)


def test_runner_run_range_invalid():
    config = ShadowRunnerConfig()
    runner = ShadowRunner(config)
    with pytest.raises(ShadowRunnerError, match="start_date.*>.*end_date"):
        runner.run_range(date(2025, 1, 10), date(2025, 1, 1))


# --- Fallback determinism test ------------------------------------------------


def test_fallback_determinism(tmp_path: Path):
    """Same inputs produce same outputs (deterministic for same seed/data)."""
    config = ShadowRunnerConfig(shadow_root=tmp_path, cps=(20,), force=True)
    record = _valid_record()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_mock_forecast_stdout(record),
            stderr="",
        )
        runner = ShadowRunner(config)
        r1 = runner.run_date(date(2025, 1, 15))
        r2 = runner.run_date(date(2025, 1, 15))

    # Both runs should produce identical records.
    assert r1.records[0].to_dict() == r2.records[0].to_dict()


# --- Default config tests -----------------------------------------------------


def test_default_config():
    config = ShadowRunnerConfig()
    assert config.cps == DEFAULT_CPS
    assert config.force is False
    assert config.timeout_s == 120


# --- Negative test scenarios (patch-forward) ----------------------------------


def test_partial_file_triggers_repair(tmp_path: Path):
    """A file with only 1 of 4 expected CPs is NOT complete -> runner repairs it.

    The mock returns records with distinct cp_utc based on the --cp argument,
    and the final JSONL is verified to have all 4 distinct CPs.
    """
    config = ShadowRunnerConfig(shadow_root=tmp_path, cps=(20, 21, 22, 23), force=False)
    target = date(2025, 1, 15)

    # Pre-create a partial file (only CP20).
    out_path = _output_path(tmp_path, target)
    out_path.parent.mkdir(parents=True)
    partial = _valid_record()
    partial["cp_utc"] = "2025-01-15T20:00:00+00:00"
    with open(out_path, "w") as fh:
        fh.write(json.dumps(partial) + "\n")

    def side_effect(*args, **kwargs):
        """Return a record with cp_utc matching the --cp argument."""
        cmd = args[0]
        cp = int(cmd[cmd.index("--cp") + 1])
        record = _valid_record()
        record["cp_utc"] = f"2025-01-15T{cp:02d}:00:00+00:00"
        return MagicMock(
            returncode=0,
            stdout=_mock_forecast_stdout(record),
            stderr="",
        )

    with patch("subprocess.run", side_effect=side_effect) as mock_subprocess:
        runner = ShadowRunner(config)
        result = runner.run_date(target)

    # Should NOT be skipped: partial file triggers repair.
    assert not result.skipped
    assert result.n_success == 4
    # subprocess.run should have been called for all 4 CPs.
    assert mock_subprocess.call_count == 4

    # Verify final JSONL has all 4 distinct CPs.
    lines = out_path.read_text(encoding="ascii").strip().split("\n")
    assert len(lines) == 4
    found_cps = set()
    for line in lines:
        rec = json.loads(line)
        cp_hour = int(rec["cp_utc"].split("T")[1].split(":")[0])
        found_cps.add(cp_hour)
    assert found_cps == {20, 21, 22, 23}


def test_is_complete_rejects_wrong_date(tmp_path: Path):
    """_is_complete() should reject a file where records have wrong date_local."""
    from core.ops.shadow_runner import _is_complete

    target = date(2025, 1, 15)
    out_path = tmp_path / "forecasts" / f"{target.isoformat()}.jsonl"
    out_path.parent.mkdir(parents=True)

    # Write records with wrong date_local.
    wrong_date = _valid_record()
    wrong_date["date_local"] = "2025-01-14"  # Wrong date!
    wrong_date["cp_utc"] = "2025-01-14T20:00:00+00:00"
    with open(out_path, "w") as fh:
        fh.write(json.dumps(wrong_date) + "\n")

    # Should be incomplete because date_local doesn't match.
    assert not _is_complete(out_path, target, (20,))


def test_is_complete_rejects_superset_of_cps(tmp_path: Path):
    """_is_complete() should reject a file with extra CPs (superset)."""
    from core.ops.shadow_runner import _is_complete

    target = date(2025, 1, 15)
    out_path = tmp_path / "forecasts" / f"{target.isoformat()}.jsonl"
    out_path.parent.mkdir(parents=True)

    # Write records with extra CPs (20, 21, 22 instead of just 20, 21).
    lines = []
    for cp in (20, 21, 22):
        rec = _valid_record()
        rec["cp_utc"] = f"2025-01-15T{cp:02d}:00:00+00:00"
        lines.append(json.dumps(rec))
    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    # Expected only (20, 21), but file has (20, 21, 22) -> not exact match.
    assert not _is_complete(out_path, target, (20, 21))


def test_is_complete_accepts_exact_cp_set(tmp_path: Path):
    """_is_complete() should accept a file with exact CP set and correct date."""
    from core.ops.shadow_runner import _is_complete

    target = date(2025, 1, 15)
    out_path = tmp_path / "forecasts" / f"{target.isoformat()}.jsonl"
    out_path.parent.mkdir(parents=True)

    # Write records with exact CPs.
    lines = []
    for cp in (20, 21, 22, 23):
        rec = _valid_record()
        rec["cp_utc"] = f"2025-01-15T{cp:02d}:00:00+00:00"
        lines.append(json.dumps(rec))
    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    assert _is_complete(out_path, target, (20, 21, 22, 23))


def test_schema_rejects_non_integer_prob_dist_keys():
    raw = _valid_record()
    raw["prob_dist"] = {"abc": 0.5, "def": 0.5}
    with pytest.raises(ShadowSchemaError, match="not an integer"):
        validate_record(raw)


def test_schema_rejects_negative_prob_dist_values():
    raw = _valid_record()
    raw["prob_dist"] = {"18": -0.1, "19": 1.1}
    with pytest.raises(ShadowSchemaError, match="negative"):
        validate_record(raw)


def test_schema_rejects_prob_dist_sum_not_one():
    raw = _valid_record()
    raw["prob_dist"] = {"18": 0.1, "19": 0.1, "20": 0.1}  # sum = 0.3
    with pytest.raises(ShadowSchemaError, match="sum is"):
        validate_record(raw)


def test_schema_rejects_invalid_date_local():
    raw = _valid_record()
    raw["date_local"] = "not-a-date"
    with pytest.raises(ShadowSchemaError, match="date_local"):
        validate_record(raw)


def test_schema_rejects_invalid_cp_utc():
    raw = _valid_record()
    raw["cp_utc"] = "not-a-datetime"
    with pytest.raises(ShadowSchemaError, match="cp_utc"):
        validate_record(raw)


def test_schema_rejects_missing_served_model():
    raw = _valid_record()
    raw["routing"] = {"model_route": "ecmwf"}  # no served_model
    with pytest.raises(ShadowSchemaError, match="served_model"):
        validate_record(raw)
