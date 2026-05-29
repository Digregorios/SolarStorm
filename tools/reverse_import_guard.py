"""Reverse-import guard (REQ-AUD-3, REQ-REP-4).

Fails if any file under ``core/`` or ``nzwn/`` imports from ``audits``,
``experiments``, or ``artifacts.scratch``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROTECTED_ROOTS = ("core", "nzwn")
FORBIDDEN_PREFIXES = ("audits", "experiments", "artifacts.scratch")


def _is_forbidden(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES)


def scan(repo_root: Path) -> list[tuple[Path, int, str]]:
    """Return a list of (file, lineno, module) violations."""
    violations: list[tuple[Path, int, str]] = []
    for root_name in PROTECTED_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            try:
                src = py.read_text(encoding="ascii")
            except UnicodeDecodeError:
                # ASCII guard handles this elsewhere; here we focus on imports.
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_forbidden(alias.name):
                            violations.append((py, node.lineno, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.module and _is_forbidden(node.module):
                        violations.append((py, node.lineno, node.module))
    return violations


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(argv[1]).resolve() if argv and len(argv) > 1 else Path.cwd()
    bad = scan(repo_root)
    if not bad:
        print("reverse-import-guard: OK")
        return 0
    print("reverse-import-guard: VIOLATIONS")
    for f, ln, mod in bad:
        try:
            rel = f.relative_to(repo_root)
        except ValueError:
            rel = f
        print(f"  {rel}:{ln}  forbidden import: {mod}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
