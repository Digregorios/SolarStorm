"""forecast --model flag: empirical default (no silent switch), ridge opt-in."""

from __future__ import annotations

import inspect

import pytest

from core.cli import forecast as fc


def test_model_param_defaults_to_empirical():
    sig = inspect.signature(fc.run)
    p = sig.parameters["model"]
    # typer OptionInfo carries the default in .default
    assert getattr(p.default, "default", p.default) == "empirical"


def test_invalid_model_rejected():
    import typer
    with pytest.raises((typer.BadParameter, Exception)):
        fc.run(target_date="2026-05-27", cp="23", model="bogus", dry_run=True)
