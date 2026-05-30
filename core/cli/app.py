"""Tmax CLI - typer app (REQ-OPS-1, REQ-OPS-2)."""

from __future__ import annotations

import typer

from core.cli import (
    audit as audit_cmd,
    decide as decide_cmd,
    forecast as forecast_cmd,
    ingest as ingest_cmd,
    postmortem as postmortem_cmd,
    report as report_cmd,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Polymarket Tmax Forecaster CLI (NZWN). ASCII-only.",
)

app.command("forecast")(forecast_cmd.run)
app.command("decide")(decide_cmd.run)
app.command("postmortem")(postmortem_cmd.run)
app.command("audit")(audit_cmd.run)
app.command("ingest-history")(ingest_cmd.ingest_history)
app.command("build-features")(ingest_cmd.build_features)
app.command("report")(report_cmd.run)


def _placeholder(name: str) -> None:  # pragma: no cover
    raise SystemExit(2)


# update-ar is a Phase 6 placeholder; keep it visible but failing with exit 2.
@app.command("update-ar")
def update_ar() -> None:
    """Phase 6 placeholder - returns exit 2."""
    raise typer.Exit(code=2)


if __name__ == "__main__":  # pragma: no cover
    app()
