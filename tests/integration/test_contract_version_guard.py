"""Integration tests for tools/contract_version_guard.py (T-X-2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.contract_version_guard import contracts_missing_version, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_flags_unversioned(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "good.md").write_text(
        "# Contract (FOO_VERSION = 1.0)\nSome text.\n", encoding="utf-8"
    )
    (contracts / "bad.md").write_text(
        "# Contract: no version here\nJust prose.\n", encoding="utf-8"
    )
    missing = contracts_missing_version(tmp_path)
    names = [p.name for p in missing]
    assert "bad.md" in names
    assert "good.md" not in names


def test_main_exit_code(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "ok.md").write_text("criterion_version = 2.0\n", encoding="utf-8")
    assert main([__file__, str(tmp_path)]) == 0
    (contracts / "nope.md").write_text("# No version\n", encoding="utf-8")
    assert main([__file__, str(tmp_path)]) == 1


def test_real_contracts_pass() -> None:
    """Every existing contract in the repo must have a version declaration."""
    missing = contracts_missing_version(REPO_ROOT)
    assert missing == [], f"Contracts missing version: {[p.name for p in missing]}"
