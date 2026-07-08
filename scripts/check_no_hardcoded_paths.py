#!/usr/bin/env python3
"""Fail if ``src/quant/`` hardcodes absolute paths in string literals.

Enforces the AGENTS.md §2 red-line ("runtime paths come from
``quant.config.Settings`` / ``.env``, never hardcoded") by machine instead of
by convention. Scope is deliberately limited to ``src/quant/`` business logic;
v1 legacy scripts under ``scripts/`` are exempt (they are ruff-excluded and take
paths via argparse defaults).

Detection is AST-based: only string-literal *values* are inspected. Module,
class and function docstrings are skipped, and ``#`` comments never enter the
AST, so documentation that merely mentions a path (e.g. a WSL2 mount note) does
not trip the gate — only an actual hardcoded value like ``x = "/home/yang/..."``
does.

Run locally::

    python scripts/check_no_hardcoded_paths.py

Also wired into ``.pre-commit-config.yaml`` and CI.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "src" / "quant"

# Absolute-path prefixes that must never be baked into business logic.
FORBIDDEN = re.compile(r"(/mnt/|/home/|[A-Za-z]:\\)")


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Return id()s of the Constant nodes that are docstrings (to skip)."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _check_file(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    skip = _docstring_ids(tree)
    rel = path.relative_to(ROOT)
    out: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
            and FORBIDDEN.search(node.value)
        ):
            out.append(f"{rel}:{node.lineno}: {node.value!r}")
    return out


def main() -> int:
    if not TARGET.exists():
        print(f"[check-hardcoded-paths] target not found: {TARGET}", file=sys.stderr)
        return 1
    violations: list[str] = []
    for path in sorted(TARGET.rglob("*.py")):
        violations.extend(_check_file(path))
    if violations:
        print(
            "Hardcoded absolute path(s) in src/quant/ string literals "
            "(use quant.config.Settings / .env instead):\n",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    print("[check-hardcoded-paths] OK: no hardcoded paths in src/quant/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
