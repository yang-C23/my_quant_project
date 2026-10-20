"""Local project/data/result inventories, without executing archived pickle files."""

from __future__ import annotations

import ast
from importlib import metadata
from pathlib import Path
import subprocess

import pandas as pd

from quant.backtest.metrics import geometric_metrics
from quant.config import Settings
from quant.data.quality import audit_daily
from quant.data.snapshots import sha256_file, tree_manifest, utc_now, write_json
from quant.etl.restart import code_revision


def audit_project(settings: Settings, project_root: Path) -> dict:
    """Freeze inventories and classify old results conservatively."""
    stamp = utc_now().replace(":", "").replace("+0000", "Z")
    out = settings.data_root / "audits" / stamp
    out.mkdir(parents=True)
    code = code_revision()
    write_json(out / "code.json", code)
    # Reproducible baseline contains only tracked files, never .env or credentials.
    with (out / "baseline-source.tar").open("wb") as target:
        subprocess.run(
            ["git", "archive", code["commit"]], cwd=project_root, stdout=target, check=True
        )
    versions = sorted(
        {
            f"{d.metadata['Name']}=={d.version}"
            for d in metadata.distributions()
            if d.metadata.get("Name")
        }
    )
    (out / "installed-versions.txt").write_text("\n".join(versions) + "\n")
    syntax = []
    for base in ("src", "scripts", "tests"):
        for path in sorted((project_root / base).rglob("*.py")):
            try:
                ast.parse(path.read_text(encoding="utf-8"))
                status = "syntax_valid"
            except (SyntaxError, UnicodeError) as exc:
                status = str(exc)
            syntax.append(
                {
                    "path": str(path.relative_to(project_root)),
                    "sha256": sha256_file(path),
                    "status": status,
                }
            )
    write_json(out / "code_inventory.json", syntax)
    write_json(
        out / "documentation_inventory.json",
        [
            {"path": str(path.relative_to(project_root)), "sha256": sha256_file(path)}
            for path in sorted(project_root.rglob("*.md"))
            if not {".git", ".venv", "node_modules"}.intersection(path.parts)
        ],
    )
    related = []
    for name in ("my_quant_project", "tdx2db", "qlib", "backtrader", "alphas", "StockTradebyZ"):
        root = project_root.parent / name
        if (root / ".git").exists():
            result = subprocess.run(
                ["git", "status", "--short", "--branch"], cwd=root, capture_output=True, text=True
            )
            related.append({"repository": name, "status": result.stdout.strip()})
    write_json(out / "related_repositories.json", related)
    worktrees = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    (out / "worktrees.txt").write_text(worktrees)
    daily = audit_daily(settings.staging_dir / "daily")
    write_json(out / "daily_quality.json", daily)
    for name, directory in (
        ("staging", settings.staging_dir),
        ("qlib_cn", settings.qlib_cn_daily_uri),
        ("tdx_mirror", settings.mirror_dir),
    ):
        if directory.exists():
            write_json(out / f"{name}_manifest.json", tree_manifest(directory))
    results = []
    for path in sorted((project_root / "backtest_results").rglob("*")):
        if not path.is_file():
            continue
        entry = {
            "path": str(path.relative_to(project_root)),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
            "status": "evidence_insufficient",
            "reason": "requires original code/config/snapshot replay",
        }
        if path.suffix == ".csv":
            try:
                header = pd.read_csv(path, nrows=0)
                if {"return", "cost"}.issubset(header.columns):
                    frame = pd.read_csv(path)
                    entry.update(
                        {
                            "status": "invalid_legacy_metric",
                            "reason": "legacy arithmetic accumulation is not account drawdown",
                            "corrected_geometric_metrics": geometric_metrics(
                                frame["return"] - frame["cost"]
                            ),
                        }
                    )
            except (ValueError, pd.errors.ParserError, UnicodeError) as exc:
                entry.update(status="needs_review", reason=str(exc))
        results.append(entry)
    write_json(out / "old_results.json", results)
    summary = {
        "audit_directory": str(out),
        "created_at": utc_now(),
        "baseline_commit": code["commit"],
        "code_files": len(syntax),
        "result_files": len(results),
        "daily": daily["summary"],
        "scope_note": "Full inventories and automated checks; semantic review tracked separately.",
    }
    write_json(out / "summary.json", summary)
    write_json(settings.data_root / "audits" / "latest.json", summary)
    return summary
