"""CLI: tmax audit (REQ-AUD-1, REQ-AUD-3).

Runs the H0 audit harness *out of process* so that ``core/cli/audit.py`` never
statically imports anything from ``audits.*`` (REQ-AUD-3 reverse-import guard).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer


def run(
    phase: str = typer.Option("all", "--phase"),
    station_yaml: Path = typer.Option(Path("nzwn/config/station.yaml"), "--station-config"),
    csv: Path = typer.Option(Path("NZWN.csv"), "--csv"),
    train_start: str = typer.Option("2020-01-01", "--train-start"),
    train_end: str = typer.Option("2024-12-31", "--train-end"),
    test_start: str = typer.Option("2025-01-01", "--test-start"),
    test_end: str = typer.Option("2025-06-30", "--test-end"),
    out_root: Path = typer.Option(Path("audits"), "--out-root"),
) -> None:
    """Forensic H0 audit harness (out of process)."""
    cmd = [
        sys.executable, "-m", "audits.run_h0_audit",
        "--phase", phase,
        "--station-config", str(station_yaml),
        "--csv", str(csv),
        "--train-start", train_start,
        "--train-end", train_end,
        "--test-start", test_start,
        "--test-end", test_end,
        "--out-root", str(out_root),
    ]
    rc = subprocess.run(cmd, check=False).returncode
    if rc != 0:
        raise typer.Exit(code=rc)


__all__ = ["run"]
