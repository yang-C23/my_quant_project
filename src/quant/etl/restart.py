"""Rebuild TDX data into a verified immutable snapshot; atomically publish last."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path
import shutil
import subprocess

import pandas as pd
import pyarrow.parquet as pq

from quant.config import Settings
from quant.data.quality import audit_daily, invalid_bars
from quant.data.snapshots import SnapshotStore, sha256_file, tree_manifest, utc_now, write_json
from quant.etl.adjust import compute_adjust
from quant.etl.basics import compute_basics
from quant.etl.mirror import extract_zip_baseline, mirror_vipdoc
from quant.etl.qlib_dump import dump_cn_daily
from quant.etl.staging import (
    _resolve_hq_cache,
    build_blocks_staging,
    build_daily_staging,
    build_gbbq_staging,
    build_securities_staging,
)

logger = logging.getLogger(__name__)
PARSER_VERSION = "tdx-units-statistics-fund-splits-v4"


def code_revision() -> dict:
    """Record revision and diff digest without copying secrets into a manifest."""
    root = Path(__file__).resolve().parents[3]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    import hashlib

    diff = subprocess.run(
        ["git", "diff", "HEAD", "--", "src", "scripts", "configs", "pyproject.toml"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    # Untracked implementation files are included in the source fingerprint.
    sources = {
        str(p.relative_to(root)): sha256_file(p)
        for prefix in ("src/quant", "scripts", "configs")
        for p in sorted((root / prefix).rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    return {"commit": head, "diff_sha256": hashlib.sha256(diff).hexdigest(), "sources": sources}


def pipeline_fingerprint() -> dict:
    """Changes to parsing/derivation also invalidate a same-source snapshot."""
    root = Path(__file__).resolve().parents[1]
    return {
        str(p.relative_to(root)): sha256_file(p)
        for name in ("etl", "data/quality.py")
        for p in (sorted((root / name).rglob("*.py")) if (root / name).is_dir() else [root / name])
    }


def _quarantine(staging: Path) -> int:
    bad_parts = []
    statistics = []
    for path in sorted((staging / "daily").rglob("*.parquet")):
        frame = pq.ParquetFile(path).read().to_pandas()
        special = frame.symbol.str.startswith(("sh8800", "sz395"))
        if special.any():
            statistics.append(frame[special].assign(field_semantics="TDX_statistics_not_OHLC"))
        frame = frame[~special].copy()
        bad = invalid_bars(frame)
        if bad.any():
            bad_parts.append(frame[bad].assign(reason="invalid_ohlc_or_activity"))
        if bad.any() or special.any():
            frame.loc[~bad].to_parquet(path, index=False, compression="zstd")
    if statistics:
        pd.concat(statistics, ignore_index=True).rename(
            columns={c: f"source_{c}_field" for c in ("open", "high", "low", "close")}
        ).to_parquet(staging / "tdx_statistics.parquet", index=False, compression="zstd")
    if bad_parts:
        directory = staging.parent / "quarantine"
        directory.mkdir(exist_ok=True)
        pd.concat(bad_parts, ignore_index=True).to_parquet(
            directory / "daily.parquet", index=False, compression="zstd"
        )
    return sum(len(part) for part in bad_parts)


def _derive(staging: Path, *, batch_size: int = 256) -> None:
    gbbq = pd.read_parquet(staging / "gbbq.parquet")
    securities = pd.read_parquet(staging / "securities.parquet")
    symbols = securities["symbol"].astype(str).tolist()
    for name in ("basics", "adjust"):
        (staging / name).mkdir(exist_ok=True)
    for offset in range(0, len(symbols), batch_size):
        batch = symbols[offset : offset + batch_size]
        daily = pd.read_parquet(staging / "daily", filters=[("symbol", "in", batch)])
        events = gbbq[gbbq["symbol"].isin(batch)]
        for name, calculate in (("basics", compute_basics), ("adjust", compute_adjust)):
            frame = calculate(daily, events)
            frame.to_parquet(
                staging / name / f"part-{offset:06}.parquet", index=False, compression="zstd"
            )
        logger.info(
            "derived %d/%d instruments", min(offset + batch_size, len(symbols)), len(symbols)
        )


def _copy_metadata(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    names = ("gbbq", "tdxhy.cfg", "tdxzs3.cfg", "infoharbor_block.dat", "needini.dat")
    selected = [source / name for name in names] + sorted(source.glob("*.tnf"))
    for path in selected:
        if path.is_file():
            shutil.copy2(path, target / path.name)


def update_snapshot(
    settings: Settings,
    *,
    workers: int = 4,
    build_qlib: bool = True,
    publish: bool = True,
    resume: str | None = None,
) -> dict:
    """Refresh complete source records per symbol, validating before publication.

    Reading all available records also detects older corrections and holes that
    per-symbol high-water marks cannot find. Baseline+current union retains history.
    Progress is resumable; no active data files are edited.
    """
    if publish and not build_qlib:
        raise ValueError("compatibility publication requires a matching Qlib cache")
    store = SnapshotStore(settings.data_root)
    fingerprint = pipeline_fingerprint()
    with store.writer_lock():
        if resume:
            snapshot_id, directory = resume, store.path(resume)
            if (directory / "manifest.json").exists():
                raise ValueError("cannot resume a sealed snapshot")
            progress = json.loads((directory / "progress.json").read_text())
            if progress.get("pipeline_fingerprint") != fingerprint:
                raise ValueError(
                    "resume requires identical parser/derivation source; start a new build"
                )
        else:
            snapshot_id, directory = store.create()
            progress = {
                "snapshot_id": snapshot_id,
                "started_at": utc_now(),
                "completed": [],
                "pipeline_fingerprint": fingerprint,
            }
        raw = directory / "raw" / "tdx"
        staging = directory / "staging"
        staging.mkdir(exist_ok=True)

        def mark(step: str) -> None:
            progress["completed"].append(step)
            write_json(directory / "progress.json", progress)
            logger.info("snapshot %s: %s complete", snapshot_id, step)

        if "source" not in progress["completed"]:
            if settings.tdx_zip and settings.tdx_zip.exists():
                # Extract into this snapshot; never mutate the pre-restart mirror.
                extract_zip_baseline(settings.tdx_zip, raw)
            elif (settings.mirror_dir / "zip_baseline").exists():
                shutil.copytree(
                    settings.mirror_dir / "zip_baseline", raw / "zip_baseline", dirs_exist_ok=True
                )
            else:
                raise FileNotFoundError("full-history TDX baseline unavailable")
            mirror_vipdoc(settings.tdx_home, raw)
            _copy_metadata(_resolve_hq_cache(settings.tdx_home), raw / "hq_cache")
            progress["source_files"] = tree_manifest(raw)
            mark("source")
        current = store.current()
        if current and not resume:
            previous = json.loads((store.path(current) / "manifest.json").read_text())
            previous_source = [
                {**row, "path": row["path"][len("raw/tdx/") :]}
                for row in previous["files"]
                if row["path"].startswith("raw/tdx/")
            ]
            if (
                previous.get("parser_version") == PARSER_VERSION
                and previous.get("pipeline_fingerprint") == fingerprint
                and previous_source == progress["source_files"]
                and store.verify(current)["ok"]
            ):
                progress["no_change_from"] = current
                write_json(directory / "progress.json", progress)
                shutil.rmtree(
                    directory / "raw"
                )  # Own redundant comparison copy; evidence is in progress.json.
                return {
                    "snapshot_id": current,
                    "published": False,
                    "unchanged": True,
                    "comparison_directory": str(directory),
                }
        if "metadata" not in progress["completed"]:
            build_gbbq_staging(raw, staging)
            build_blocks_staging(raw, staging)
            mark("metadata")
        if "daily" not in progress["completed"]:
            progress["parse"] = asdict(build_daily_staging(raw, staging, workers=workers))
            if progress["parse"]["files_failed"] or progress["parse"]["records_skipped"]:
                raise ValueError("source parse failures; snapshot not published")
            progress["quarantined_rows"] = _quarantine(staging)
            mark("daily")
        if "securities" not in progress["completed"]:
            build_securities_staging(staging, tdx_root=raw)
            mark("securities")
        if "derived" not in progress["completed"]:
            _derive(staging)
            mark("derived")
        if build_qlib and "qlib" not in progress["completed"]:
            progress["qlib"] = asdict(dump_cn_daily(staging, directory / "qlib" / "cn_daily"))
            mark("qlib")
        checks = audit_daily(staging / "daily")
        if not checks["summary"]["structurally_valid"]:
            raise ValueError("daily structural validation failed")
        write_json(directory / "quality.json", checks)
        metadata = {
            "publication_status": "validated",
            "research_grade": "exploratory",
            "source": "user_tdx",
            "parser_version": PARSER_VERSION,
            "pipeline_fingerprint": fingerprint,
            "previous_snapshot_id": store.current() or "legacy",
            "code": code_revision(),
            "quality": checks["summary"],
            "quarantined_rows": progress.get("quarantined_rows", 0),
            "qlib_built": build_qlib,
            "known_limitations": [
                "TDX corporate actions lack announced_at and dividend payment dates",
                "category11 split ratios applied; category12 nontradable-share changes are not price splits",
                "leveraged/structured fund conversions need individual rights and cashflow review",
                "historical revisions are not point-in-time vintages",
                "security listing/delisting dates inferred from coverage, not official lifecycle",
                "stock historical ST/limit flags not certified; omitted from this snapshot",
                "ETF units corroborated on 2026-10-19; older intervals still require sampling",
                "TDX activity fields have finite storage precision; not exact exchange unit counts",
                "bond/repo/other-security units are not certified for investment research",
                "public index valuation history and ETF dividend evidence need separate acceptance",
            ],
        }
        store.seal(snapshot_id, metadata)
        if publish:
            if not build_qlib:
                raise ValueError("compatibility publication requires a matching Qlib cache")
            store.activate(snapshot_id)
        return {"snapshot_id": snapshot_id, "published": publish, **checks["summary"]}
