"""ASCII guard tests (REQ-OPS-2)."""

from __future__ import annotations

from pathlib import Path

from tools.ascii_guard import scan


def test_repo_has_no_unicode_in_protected_roots():
    repo = Path(__file__).resolve().parents[2]
    bad = scan(repo)
    bad_msgs = [(str(p), reason) for p, reason in bad]
    assert bad == [], f"Unexpected non-ASCII content/paths: {bad_msgs}"


def test_negative_case_unicode_content(tmp_path: Path):
    (tmp_path / "core").mkdir()
    bad = tmp_path / "core" / "u.py"
    # Write bytes that contain a UTF-8 sequence (e-acute = 0xC3 0xA9). The
    # source of this test stays pure ASCII because we use \xHH escapes.
    payload = b"# encoding test\nx = 'caf\xc3\xa9'\n"
    bad.write_bytes(payload)
    found = scan(tmp_path)
    assert found, "Expected the unicode content to be detected"
