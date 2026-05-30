"""ASCII-only guard (REQ-OPS-2).

Fails if:
- any path under ``core/``, ``nzwn/``, ``audits/``, ``contracts/``, ``tools/``, ``tests/``
  contains non-ASCII characters,
- any ``*.py`` / ``*.md`` / ``*.yaml`` / ``*.yml`` / ``*.toml`` / ``*.ini`` / ``*.jsonl`` file
  in those roots contains non-ASCII bytes (excluding directories like
  ``references/legacy/``).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOTS = ("core", "nzwn", "audits", "contracts", "tools", "tests")
EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".toml", ".ini", ".jsonl"}
_MAX_READ_BYTES = 10 * 1024 * 1024  # 10 MiB guard against OOM


def _is_ascii(text: bytes) -> bool:
    try:
        text.decode("ascii")
    except UnicodeDecodeError:
        return False
    return True


def scan(repo_root: Path) -> list[tuple[Path, str]]:
    bad: list[tuple[Path, str]] = []
    for r in ROOTS:
        root = repo_root / r
        if not root.exists():
            continue
        for p in root.rglob("*"):
            try:
                rel = str(p.relative_to(repo_root))
            except ValueError:
                rel = str(p)
            try:
                rel.encode("ascii")
            except UnicodeEncodeError:
                bad.append((p, "non-ascii path"))
                continue
            if p.is_file() and p.suffix.lower() in EXTENSIONS:
                try:
                    if p.stat().st_size > _MAX_READ_BYTES:
                        continue
                    raw = p.read_bytes()
                except OSError:
                    continue
                if not _is_ascii(raw):
                    bad.append((p, "non-ascii content"))
    return bad


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(argv[1]).resolve() if argv and len(argv) > 1 else Path.cwd()
    bad = scan(repo_root)
    if not bad:
        print("ascii-guard: OK")
        return 0
    print("ascii-guard: VIOLATIONS")
    for p, reason in bad:
        try:
            rel = p.relative_to(repo_root)
        except ValueError:
            rel = p
        print(f"  {rel}  {reason}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
