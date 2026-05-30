"""Contract version guard (T-X-2).

Fails if any contracts/*.md file has no detectable version declaration.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Matches lines like:
#   (Q_VERSION = 1.0)
#   EXECUTION_VERSION = 1.0
#   criterion_version = 1.1
#   conformal_method_version 1.2
#   q_version 1.1
_VERSION_RE = re.compile(
    r"[A-Za-z_]*[Vv][Ee][Rr][Ss][Ii][Oo][Nn]\s*[=: ]\s*\d"
)


def contracts_missing_version(root: Path) -> list[Path]:
    """Return contract .md files under root/contracts/ with no version token."""
    contracts_dir = root / "contracts"
    if not contracts_dir.is_dir():
        return []
    missing: list[Path] = []
    for md in sorted(contracts_dir.glob("*.md")):
        if not md.is_file():
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            missing.append(md)
            continue
        if not _VERSION_RE.search(text):
            missing.append(md)
    return missing


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(argv[1]).resolve() if argv and len(argv) > 1 else Path.cwd()
    bad = contracts_missing_version(repo_root)
    if not bad:
        print("contract-version-guard: OK")
        return 0
    print("contract-version-guard: VIOLATIONS")
    for p in bad:
        try:
            rel = p.relative_to(repo_root)
        except ValueError:
            rel = p
        print(f"  {rel}  missing version declaration")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
