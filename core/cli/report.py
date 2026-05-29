"""CLI: tmax report (placeholder for Phase 5+ rich reports)."""

from __future__ import annotations

import typer


def run(
    kind: str = typer.Option("coverage", "--kind"),
    window: str = typer.Option("30d", "--window"),
) -> None:
    """Phase 5+ placeholder: returns exit 2 with a clear message."""
    typer.echo(f"report kind={kind} window={window} - not implemented in Phase 1/2")
    raise typer.Exit(code=2)


__all__ = ["run"]
