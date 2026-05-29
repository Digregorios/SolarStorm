"""Reverse-import guard tests (REQ-AUD-3)."""

from __future__ import annotations

from pathlib import Path

from tools.reverse_import_guard import scan


def test_no_violations_in_repo():
    repo = Path(__file__).resolve().parents[2]
    violations = scan(repo)
    assert violations == [], f"Unexpected reverse-import violations: {violations}"


def test_detects_negative_case(tmp_path: Path):
    (tmp_path / "core").mkdir()
    bad = tmp_path / "core" / "bad.py"
    bad.write_text(
        "from audits.run_h0_audit import run_audit\n",
        encoding="ascii",
    )
    violations = scan(tmp_path)
    assert violations, "Expected to detect the forbidden import"
    assert any(v[2].startswith("audits") for v in violations)


def test_detects_experiments_import(tmp_path: Path):
    (tmp_path / "nzwn").mkdir()
    bad = tmp_path / "nzwn" / "bad.py"
    bad.write_text(
        "import experiments.foo\n",
        encoding="ascii",
    )
    violations = scan(tmp_path)
    assert any(v[2].startswith("experiments") for v in violations)
