"""Build Parquet staging tables from mirrored TDX binary files.

Daily bars: see docs/data_platform.md §3 for the 32-byte .day record layout
and §4 for the staging schema. Parsing is vectorized via ``np.frombuffer``;
invalid records are skipped (warn + count), never silently dropped.
"""

from __future__ import annotations

import logging
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant.etl.tdx_parser import collect_day_files

logger = logging.getLogger(__name__)

RECORD_SIZE = 32

DAY_DTYPE = np.dtype(
    [
        ("date", "<u4"),
        ("open", "<u4"),
        ("high", "<u4"),
        ("low", "<u4"),
        ("close", "<u4"),
        ("amount", "<f4"),
        ("volume", "<u4"),
        ("reserved", "<u4"),
    ]
)

DAILY_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string()),
        pa.field("date", pa.date32()),
        pa.field("open", pa.float64()),
        pa.field("high", pa.float64()),
        pa.field("low", pa.float64()),
        pa.field("close", pa.float64()),
        pa.field("volume", pa.int64()),
        pa.field("amount", pa.float64()),
    ]
)

_CHUNK_SIZE = 128  # files per worker task


@dataclass
class StagingStats:
    """Outcome of a staging build."""

    files_total: int = 0
    files_failed: int = 0
    rows: int = 0
    rows_deduped: int = 0
    records_skipped: int = 0
    seconds: float = 0.0
    by_exchange: dict[str, int] = field(default_factory=dict)


def parse_day_bytes(buf: bytes, symbol: str) -> pd.DataFrame:
    """Vectorized parse of raw .day bytes into a daily-bar DataFrame.

    Returns columns symbol/date/open/high/low/close/volume/amount (see
    ``DAILY_SCHEMA``); prices are ``uint32/100`` yuan, volume shares,
    amount yuan. Records with invalid dates and any trailing partial
    record are skipped; the skip count is exposed as
    ``df.attrs["n_skipped"]`` (read it before further transforms —
    pandas does not propagate attrs reliably).
    """
    usable = len(buf) - (len(buf) % RECORD_SIZE)
    n_skipped = 1 if usable != len(buf) else 0
    raw = np.frombuffer(buf, dtype=DAY_DTYPE, count=usable // RECORD_SIZE)

    dates = pd.to_datetime(pd.Series(raw["date"]), format="%Y%m%d", errors="coerce")
    valid = dates.notna() & (raw["date"] >= 19900101)
    n_skipped += int((~valid).sum())

    df = pd.DataFrame(
        {
            "symbol": symbol,
            "date": dates[valid].dt.date.to_numpy(),
            "open": raw["open"][valid.to_numpy()] / 100.0,
            "high": raw["high"][valid.to_numpy()] / 100.0,
            "low": raw["low"][valid.to_numpy()] / 100.0,
            "close": raw["close"][valid.to_numpy()] / 100.0,
            "volume": raw["volume"][valid.to_numpy()].astype(np.int64),
            "amount": raw["amount"][valid.to_numpy()].astype(np.float64),
        }
    )
    df.attrs["n_skipped"] = n_skipped
    return df


def _parse_symbol_group(
    items: list[tuple[str, list[str]]],
) -> tuple[pd.DataFrame | None, int, int, int]:
    """Worker: parse a chunk of (symbol, [paths, baseline→newest]) groups.

    Rows for the same date across sources are deduplicated keeping the
    later-listed source (vipdoc overrides zip baseline). Returns
    (frame or None, files_failed, records_skipped, rows_deduped).
    """
    frames: list[pd.DataFrame] = []
    failed = 0
    skipped = 0
    deduped = 0
    for symbol, paths in items:
        parts: list[pd.DataFrame] = []
        for filepath in paths:
            try:
                df = parse_day_bytes(Path(filepath).read_bytes(), symbol)
                skipped += df.attrs["n_skipped"]
                if not df.empty:
                    parts.append(df)
            except Exception:  # noqa: BLE001 — per-file tolerance, counted and reported
                logger.warning("failed to parse %s", filepath, exc_info=True)
                failed += 1
        if not parts:
            continue
        merged = pd.concat(parts, ignore_index=True)
        before = len(merged)
        merged = (
            merged.drop_duplicates(subset="date", keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
        deduped += before - len(merged)
        frames.append(merged)
    if not frames:
        return None, failed, skipped, deduped
    return pd.concat(frames, ignore_index=True), failed, skipped, deduped


def _collect_symbol_sources(mirror_dir: Path) -> dict[str, list[str]]:
    """Map symbol → ordered source files (zip baseline first, vipdoc last)."""
    sources: dict[str, list[str]] = {}
    for root in (mirror_dir / "zip_baseline", mirror_dir / "vipdoc"):
        if root.is_dir():
            for path, symbol in collect_day_files(root):
                sources.setdefault(symbol, []).append(str(path))
    return dict(sorted(sources.items()))


def build_daily_staging(mirror_dir: Path, staging_dir: Path, *, workers: int = 20) -> StagingStats:
    """Parse all mirrored .day files into ``staging/daily/exchange=*/`` Parquet.

    Sources are unioned per symbol (vipdoc wins on overlapping dates, see
    docs/data_platform.md §2). Symbols are processed in sorted order so
    output row groups are naturally sorted by (symbol, date). Existing
    daily staging is replaced (full load).
    """
    t0 = time.monotonic()
    stats = StagingStats()

    sources = _collect_symbol_sources(mirror_dir)
    stats.files_total = sum(len(paths) for paths in sources.values())
    if not sources:
        raise FileNotFoundError(f"no .day files under {mirror_dir} (zip_baseline/ or vipdoc/)")

    daily_root = staging_dir / "daily"
    if daily_root.exists():
        shutil.rmtree(daily_root)

    by_exchange: dict[str, list[tuple[str, list[str]]]] = {}
    for symbol, paths in sources.items():
        by_exchange.setdefault(symbol[:2], []).append((symbol, paths))

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for exchange, items in sorted(by_exchange.items()):
            out_dir = daily_root / f"exchange={exchange}"
            out_dir.mkdir(parents=True, exist_ok=True)
            chunks = [items[i : i + _CHUNK_SIZE] for i in range(0, len(items), _CHUNK_SIZE)]
            rows = 0
            with pq.ParquetWriter(
                out_dir / "part-000.parquet", DAILY_SCHEMA, compression="zstd"
            ) as writer:
                for frame, failed, skipped, deduped in pool.map(_parse_symbol_group, chunks):
                    stats.files_failed += failed
                    stats.records_skipped += skipped
                    stats.rows_deduped += deduped
                    if frame is None:
                        continue
                    writer.write_table(
                        pa.Table.from_pandas(frame, schema=DAILY_SCHEMA, preserve_index=False)
                    )
                    rows += len(frame)
            stats.by_exchange[exchange] = rows
            stats.rows += rows
            logger.info("exchange=%s: %d rows from %d symbols", exchange, rows, len(items))

    stats.seconds = time.monotonic() - t0
    return stats
