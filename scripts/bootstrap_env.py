#!/usr/bin/env python3
"""Create a checkout-local environment without modifying shared installations."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Create an isolated worktree environment and install pinned dependencies."""
    target = ROOT / ".venv"
    if not (target / "pyvenv.cfg").exists():
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(target)
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    command = [
        str(target / "bin/python"),
        "-m",
        "pip",
        "install",
        "--constraint",
        str(
            ROOT / "requirements-lock.txt"
            if (ROOT / "requirements-lock.txt").exists()
            else ROOT / "requirements-runtime.txt"
        ),
        "-e",
        f"{ROOT}[dev,data]",
    ]
    subprocess.run(command, env=env, check=True)
    subprocess.run([str(ROOT / "scripts/quant"), "doctor"], env=env, check=True)


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        raise SystemExit("Python >=3.10 is required")
    main()
