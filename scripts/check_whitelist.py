#!/usr/bin/env python3
"""Fail if a task branch changes files outside its card's ``Files to touch``.

Enforces the workflow.md / AGENTS.md §4-§5 file-whitelist discipline by machine.
The task id is inferred from the branch name (``task/TASK-XXX-<slug>``) unless
``--task`` is given. The card's ``## Files to touch`` section is parsed for
repo-relative paths (one per line, backtick-wrapped per TASK-TEMPLATE.md; a
directory entry ends with ``/`` and allows anything beneath it). The card file
itself and ``docs/tasks/STATUS.md`` are always allowed.

Usage::

    python scripts/check_whitelist.py                      # infer task, base=v2
    python scripts/check_whitelist.py --task TASK-067 --base origin/v2

Runs in CI on ``task/**`` branches and can be run locally by the reviewer.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_RE = re.compile(r"TASK-\d+")
BACKTICK_RE = re.compile(r"`([^`]+)`")
PATH_EXT_RE = re.compile(r"\.(py|md|toml|yaml|yml|cfg|ini|txt|json|sh)$")
ALWAYS_ALLOWED = {"docs/tasks/STATUS.md"}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _looks_like_path(tok: str) -> bool:
    return "/" in tok or bool(PATH_EXT_RE.search(tok))


def infer_task() -> str | None:
    m = TASK_RE.search(git("rev-parse", "--abbrev-ref", "HEAD"))
    return m.group(0) if m else None


def find_card(task: str) -> Path:
    matches = sorted((ROOT / "docs" / "tasks").glob(f"{task}-*.md"))
    if not matches:
        sys.exit(f"[check-whitelist] no card found for {task} in docs/tasks/")
    return matches[0]


def parse_whitelist(card: Path) -> list[str]:
    inside = False
    paths: set[str] = set()
    for line in card.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("## "):
            inside = line.strip().lower().startswith("## files to touch")
            continue
        if not inside:
            continue
        toks = BACKTICK_RE.findall(line)
        if not toks:
            bare = line.strip().lstrip("-*> ").strip()
            toks = [bare] if bare else []
        for tok in toks:
            tok = tok.strip().rstrip(",;，、").strip()
            if _looks_like_path(tok):
                paths.add(tok)
    return sorted(paths)


def is_allowed(changed: str, whitelist: list[str], card_rel: str) -> bool:
    if changed in ALWAYS_ALLOWED or changed == card_rel:
        return True
    for entry in whitelist:
        if entry.endswith("/") and changed.startswith(entry):
            return True
        if changed == entry:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", help="TASK-XXX (default: infer from branch name)")
    ap.add_argument("--base", default="v2", help="base ref to diff against (default: v2)")
    args = ap.parse_args()

    task = args.task or infer_task()
    if task is None:
        print("[check-whitelist] not a task branch (no TASK-XXX in branch); skipping.")
        return 0

    card = find_card(task)
    card_rel = str(card.relative_to(ROOT))
    whitelist = parse_whitelist(card)
    if not whitelist:
        sys.exit(f"[check-whitelist] {card_rel}: empty/unparseable '## Files to touch'.")

    changed = [f for f in git("diff", "--name-only", f"{args.base}...HEAD").splitlines() if f]
    violations = [f for f in changed if not is_allowed(f, whitelist, card_rel)]

    if violations:
        print(f"Files changed outside {task} whitelist:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print("\nAllowed (card '## Files to touch' + STATUS.md + the card):", file=sys.stderr)
        for w in whitelist:
            print(f"  {w}", file=sys.stderr)
        return 1

    print(f"[check-whitelist] OK: {len(changed)} changed file(s) within {task} whitelist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
