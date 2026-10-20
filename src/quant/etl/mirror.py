"""Mirror TDX daily-bar sources from the Windows mount to native ext4.

Two sources (docs/data_platform.md §2-3):
- ``TDX_ZIP`` full-history archive → ``mirror/zip_baseline/`` (baseline);
- ``TDX_HOME/vipdoc`` live directories → ``mirror/vipdoc/`` (recent data).

WSL2 9P rule: full loads must never random-read /mnt/d in parallel; instead
bulk-copy sequentially (tar pipe / single zip stream) once, then parse the
local mirror.
"""

from __future__ import annotations

import logging
import hashlib
import re
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_EXCHANGES = ("sh", "sz", "bj")


@dataclass
class MirrorStats:
    """Outcome of a mirror refresh."""

    files: int = 0
    bytes: int = 0
    seconds: float = 0.0


def _lday_rel_paths(tdx_home: Path) -> list[str]:
    rels = []
    for exchange in _EXCHANGES:
        if (tdx_home / "vipdoc" / exchange / "lday").is_dir():
            rels.append(f"vipdoc/{exchange}/lday")
    return rels


def mirror_vipdoc(tdx_home: Path, mirror_dir: Path) -> MirrorStats:
    """Full refresh of ``mirror_dir/vipdoc/{sh,sz,bj}/lday`` from *tdx_home*.

    Uses a tar pipe (sequential large-block IO over 9P); falls back to
    ``shutil.copytree`` when tar is unavailable. The previous mirror content
    is replaced.
    """
    t0 = time.monotonic()
    rels = _lday_rel_paths(tdx_home)
    if not rels:
        raise FileNotFoundError(f"no vipdoc/*/lday directories under {tdx_home}")

    target_vipdoc = mirror_dir / "vipdoc"
    if target_vipdoc.exists():
        shutil.rmtree(target_vipdoc)
    mirror_dir.mkdir(parents=True, exist_ok=True)

    if shutil.which("tar"):
        src = subprocess.Popen(
            ["tar", "-C", str(tdx_home), "-cf", "-", *rels], stdout=subprocess.PIPE
        )
        dst = subprocess.run(
            ["tar", "-C", str(mirror_dir), "-xf", "-"], stdin=src.stdout, check=False
        )
        src.stdout.close()  # type: ignore[union-attr]
        src_rc = src.wait()
        if src_rc != 0 or dst.returncode != 0:
            raise RuntimeError(f"tar mirror failed (src={src_rc}, dst={dst.returncode})")
    else:  # pragma: no cover — tar is present on all target machines
        for rel in rels:
            shutil.copytree(tdx_home / rel, mirror_dir / rel)

    stats = MirrorStats()
    for path in target_vipdoc.rglob("*.day"):
        stats.files += 1
        stats.bytes += path.stat().st_size
    stats.seconds = time.monotonic() - t0
    logger.info(
        "mirrored %d files (%.1f MB) in %.1fs", stats.files, stats.bytes / 1e6, stats.seconds
    )
    return stats


_DAY_ENTRY_RE = re.compile(r"(sh|sz|bj)\d{6}\.day$", re.IGNORECASE)


def extract_zip_baseline(zip_path: Path, mirror_dir: Path) -> MirrorStats:
    """Extract all .day entries of the full-history archive to the mirror.

    Archive entry names use Windows backslashes (e.g. ``sh\\lday\\sh600000.day``);
    they are normalized and flattened to ``mirror/zip_baseline/<basename>.day``
    (basenames are globally unique: exchange prefix + 6-digit code). Existing
    baseline content is replaced. Extraction is skipped (cache hit) when the
    baseline is already complete for this archive.
    """
    t0 = time.monotonic()
    target = mirror_dir / "zip_baseline"

    with zipfile.ZipFile(zip_path) as zf:
        entries = [i for i in zf.infolist() if _DAY_ENTRY_RE.search(i.filename)]
        if not entries:
            raise ValueError(f"no .day entries in {zip_path}")

        stats = MirrorStats()
        marker = target / ".complete"
        signature = "\n".join(f"{item.filename}:{item.file_size}:{item.CRC}" for item in entries)
        fingerprint = hashlib.sha256(signature.encode()).hexdigest()
        if marker.exists() and marker.read_text() == fingerprint:
            for path in target.glob("*.day"):
                stats.files += 1
                stats.bytes += path.stat().st_size
            stats.seconds = time.monotonic() - t0
            logger.info("zip baseline cache hit (%d files), skip extraction", stats.files)
            return stats

        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for info in entries:
            basename = info.filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
            (target / basename).write_bytes(zf.read(info))
            stats.files += 1
            stats.bytes += info.file_size
        marker.write_text(fingerprint)

    stats.seconds = time.monotonic() - t0
    logger.info(
        "extracted %d baseline files (%.1f MB) in %.1fs",
        stats.files,
        stats.bytes / 1e6,
        stats.seconds,
    )
    return stats
