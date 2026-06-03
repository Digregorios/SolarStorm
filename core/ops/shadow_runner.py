"""Shadow Runner: executes forecasts for CP20-23 over date ranges (Phase 5.1).

Design:
- Uses subprocess.run to invoke `tmax forecast --model auto --serve-residuals`
- Output: artifacts/shadow_ops/forecasts/{date_local}.jsonl (one file per date)
- Atomic writes: write to .tmp then rename
- Idempotent: skip if output file already exists (with force=True to override)
- Schema validation: each record validated against REQUIRED_FORECAST_FIELDS
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from core.ops.schemas import ShadowForecastRecord, ShadowSchemaError, validate_record


# Default checkpoints to run (CP20-23 = 20:00, 21:00, 22:00, 23:00 UTC).
DEFAULT_CPS: tuple[int, ...] = (20, 21, 22, 23)

# Default output root for shadow ops artifacts.
DEFAULT_SHADOW_ROOT = Path("artifacts/shadow_ops")


@dataclass(frozen=True)
class ShadowRunnerConfig:
    """Configuration for the shadow runner.

    Attributes:
        shadow_root: Root directory for shadow ops output.
        cps: Tuple of checkpoint hours (UTC) to run.
        force: If True, overwrite existing output files.
        timeout_s: Subprocess timeout in seconds.
        python_executable: Python interpreter to use (default: sys.executable).
    """

    shadow_root: Path = DEFAULT_SHADOW_ROOT
    cps: tuple[int, ...] = DEFAULT_CPS
    force: bool = False
    timeout_s: int = 120
    python_executable: str = field(default_factory=lambda: sys.executable)


@dataclass(frozen=True)
class ShadowRunResult:
    """Result of running forecasts for a single date.

    Attributes:
        date_local: The date that was forecasted.
        output_path: Path to the JSONL output file (if written).
        records: List of validated forecast records.
        skipped: If True, the date was skipped (already exists).
        errors: List of (cp, error_message) tuples for failed checkpoints.
    """

    date_local: date
    output_path: Path | None = None
    records: list[ShadowForecastRecord] = field(default_factory=list)
    skipped: bool = False
    errors: list[tuple[int, str]] = field(default_factory=list)

    @property
    def n_success(self) -> int:
        return len(self.records)

    @property
    def n_failed(self) -> int:
        return len(self.errors)


class ShadowRunnerError(Exception):
    """Raised when the shadow runner encounters a fatal error."""


def _output_path(shadow_root: Path, d: date) -> Path:
    """Compute the output JSONL path for a given date."""
    forecasts_dir = shadow_root / "forecasts"
    return forecasts_dir / f"{d.isoformat()}.jsonl"


def _build_forecast_command(
    python_exec: str,
    target_date: date,
    cp: int,
    out_root: Path,
) -> list[str]:
    """Build the subprocess command for a single forecast."""
    return [
        python_exec,
        "-m",
        "tmax",
        "forecast",
        "--date",
        target_date.isoformat(),
        "--cp",
        str(cp),
        "--model",
        "auto",
        "--serve-residuals",
        "--out-root",
        str(out_root),
        "--dry-run",
    ]


def _parse_forecast_output(stdout: str) -> dict:
    """Parse the JSON output from `tmax forecast --dry-run`.

    The forecast CLI sends the routing banner to stderr and the JSON record to
    stdout. We find the first '{' which starts the JSON object.
    """
    start = stdout.find("{")
    if start == -1:
        raise ShadowRunnerError(f"No JSON found in forecast output: {stdout[:200]}")
    return json.loads(stdout[start:])


def _atomic_write(path: Path, lines: list[str]) -> None:
    """Write lines to a file atomically (write to .tmp, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="ascii") as fh:
        for line in lines:
            fh.write(line + "\n")
    tmp_path.replace(path)


def _is_complete(
    jsonl_path: Path,
    expected_date: date,
    expected_cps: tuple[int, ...],
) -> bool:
    """Check if a JSONL file has valid records for ALL expected CPs on the expected date.

    A file is 'complete' when it has exactly len(expected_cps) valid records,
    each with:
    - A distinct CP hour matching the expected set (exact match, not superset)
    - date_local matching the expected_date

    Partial files (fewer CPs, wrong date, or records that fail schema validation)
    are NOT complete.

    Args:
        jsonl_path: Path to the JSONL file.
        expected_date: The date_local that all records must have.
        expected_cps: Tuple of expected CP hours (UTC).
    """
    if not jsonl_path.exists():
        return False
    found_cps: set[int] = set()
    expected_date_iso = expected_date.isoformat()
    try:
        with open(jsonl_path, "r", encoding="ascii") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                validate_record(raw)
                # Validate date_local matches expected date.
                record_date = str(raw.get("date_local", ""))
                if record_date != expected_date_iso:
                    return False  # Wrong date -> not complete.
                # Extract CP hour from cp_utc.
                cp_utc_str = str(raw.get("cp_utc", ""))
                if "T" in cp_utc_str:
                    hour = int(cp_utc_str.split("T")[1].split(":")[0])
                    found_cps.add(hour)
    except (json.JSONDecodeError, ShadowSchemaError, ValueError, KeyError, OSError):
        return False  # Any parse/validation error -> not complete
    # Exact set match: all expected CPs present, no extras.
    return found_cps == set(expected_cps)


class ShadowRunner:
    """Executes forecasts for CP20-23 over date ranges.

    Usage:
        runner = ShadowRunner(config)
        result = runner.run_date(date(2025, 1, 15))
        results = runner.run_range(date(2025, 1, 1), date(2025, 1, 7))
    """

    def __init__(self, config: ShadowRunnerConfig | None = None) -> None:
        self.config = config or ShadowRunnerConfig()
        self._forecasts_out = self.config.shadow_root / "forecasts"
        self._forecasts_out.mkdir(parents=True, exist_ok=True)

    def run_date(self, target_date: date) -> ShadowRunResult:
        """Run forecasts for all configured CPs on a single date.

        Args:
            target_date: The local date to forecast.

        Returns:
            ShadowRunResult with records and/or errors.
        """
        out_path = _output_path(self.config.shadow_root, target_date)

        # Idempotency check: only skip if file has ALL expected CPs with valid schema
        # AND the date_local in records matches the target date.
        # Partial files (missing CPs or invalid records) trigger repair.
        if out_path.exists() and not self.config.force:
            if _is_complete(out_path, target_date, self.config.cps):
                return ShadowRunResult(date_local=target_date, skipped=True)
            # Partial file -> repair: re-run all CPs.

        records: list[ShadowForecastRecord] = []
        errors: list[tuple[int, str]] = []
        jsonl_lines: list[str] = []

        for cp in self.config.cps:
            try:
                record = self._run_single_cp(target_date, cp)
                records.append(record)
                jsonl_lines.append(json.dumps(record.to_dict(), ensure_ascii=True))
            except (ShadowRunnerError, ShadowSchemaError, subprocess.TimeoutExpired,
                    subprocess.CalledProcessError, OSError) as exc:
                errors.append((cp, f"{type(exc).__name__}: {exc}"))

        # Write output if we have at least one success.
        written_path: Path | None = None
        if jsonl_lines:
            _atomic_write(out_path, jsonl_lines)
            written_path = out_path

        return ShadowRunResult(
            date_local=target_date,
            output_path=written_path,
            records=records,
            errors=errors,
        )

    def _run_single_cp(self, target_date: date, cp: int) -> ShadowForecastRecord:
        """Run forecast for a single checkpoint.

        Args:
            target_date: The local date to forecast.
            cp: Checkpoint hour (UTC).

        Returns:
            Validated ShadowForecastRecord.

        Raises:
            ShadowRunnerError: If the forecast command fails.
            ShadowSchemaError: If the output fails validation.
        """
        cmd = _build_forecast_command(
            self.config.python_executable,
            target_date,
            cp,
            self._forecasts_out,
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_s,
            check=False,
        )

        if result.returncode != 0:
            stderr_snippet = result.stderr[:500] if result.stderr else "(no stderr)"
            raise ShadowRunnerError(
                f"Forecast failed for CP{cp}: exit {result.returncode}, stderr: {stderr_snippet}"
            )

        # Parse the JSON output from --dry-run.
        raw_record = _parse_forecast_output(result.stdout)

        # Validate schema.
        return validate_record(raw_record)

    def run_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[ShadowRunResult]:
        """Run forecasts for a date range (inclusive).

        Args:
            start_date: First date to run.
            end_date: Last date to run (inclusive).

        Returns:
            List of ShadowRunResult, one per date.
        """
        if start_date > end_date:
            raise ShadowRunnerError(f"start_date {start_date} > end_date {end_date}")

        results: list[ShadowRunResult] = []
        current = start_date
        while current <= end_date:
            results.append(self.run_date(current))
            current = date.fromordinal(current.toordinal() + 1)
        return results


__all__ = [
    "DEFAULT_CPS",
    "DEFAULT_SHADOW_ROOT",
    "ShadowRunner",
    "ShadowRunnerConfig",
    "ShadowRunnerError",
    "ShadowRunResult",
]
