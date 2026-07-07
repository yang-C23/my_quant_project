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

from quant.etl.blocks import parse_holidays, parse_infoharbor_blocks, parse_tdxhy, parse_tdxzs3
from quant.etl.gbbq import decode_gbbq_file
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

FLAGS_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string()),
        pa.field("date", pa.date32()),
        pa.field("is_suspended", pa.bool_()),
        pa.field("is_st", pa.bool_()),
        pa.field("limit_up_price", pa.float64()),
        pa.field("limit_down_price", pa.float64()),
        pa.field("is_limit_up", pa.bool_()),
        pa.field("is_limit_down", pa.bool_()),
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


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, compression="zstd")


def _read_staging_table(staging_dir: Path, name: str) -> pd.DataFrame:
    directory = staging_dir / name
    if directory.exists():
        return pd.read_parquet(directory)
    file_path = staging_dir / f"{name}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    raise FileNotFoundError(f"missing staging table: {directory} or {file_path}")


def gbbq_records_to_frame(records: list[tuple]) -> pd.DataFrame:
    """Convert decoded GBBQ records to the staging schema."""
    df = pd.DataFrame(records, columns=["category", "symbol", "date", "c1", "c2", "c3", "c4"])
    if df.empty:
        return pd.DataFrame(
            {
                "category": pd.Series(dtype="int16"),
                "symbol": pd.Series(dtype="string"),
                "date": pd.Series(dtype="object"),
                "c1": pd.Series(dtype="float64"),
                "c2": pd.Series(dtype="float64"),
                "c3": pd.Series(dtype="float64"),
                "c4": pd.Series(dtype="float64"),
            }
        )
    df["category"] = df["category"].astype("int16")
    df["symbol"] = df["symbol"].astype("string")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for col in ("c1", "c2", "c3", "c4"):
        df[col] = df[col].astype("float64")
    return df.sort_values(["symbol", "date", "category"]).reset_index(drop=True)


def _resolve_hq_cache(root: Path) -> Path:
    candidates = [
        root / "T0002" / "hq_cache",
        root / "hq_cache",
        root,
    ]
    for candidate in candidates:
        if any((candidate / name).exists() for name in ("gbbq", "tdxhy.cfg", "tdxzs3.cfg")):
            return candidate
    raise FileNotFoundError(f"cannot locate TDX hq_cache under {root}")


def build_gbbq_staging(tdx_home_or_mirror: Path, staging_dir: Path) -> int:
    """Decode TDX GBBQ records into ``staging/gbbq.parquet``."""
    hq_cache = _resolve_hq_cache(tdx_home_or_mirror)
    records = decode_gbbq_file(hq_cache / "gbbq")
    df = gbbq_records_to_frame(records)
    _write_parquet(df, staging_dir / "gbbq.parquet")
    return len(df)


def _classify_security(symbol: str) -> tuple[str, str]:
    exchange = symbol[:2]
    code = symbol[2:]

    if exchange == "sh" and code.startswith(("000", "999")):
        return "index", "index"
    if exchange == "sz" and code.startswith("399"):
        return "index", "index"
    if exchange == "bj" and code.startswith("899"):
        return "index", "index"
    if exchange == "sh" and code.startswith("51"):
        return "etf", "etf"
    if exchange == "sz" and code.startswith(("15", "16")):
        return "etf", "etf"

    if exchange == "bj" or code.startswith(("43", "83", "87", "920")):
        return "stock", "bse"
    if code.startswith(("300", "301")):
        return "stock", "gem"
    if code.startswith(("688", "689")):
        return "stock", "star"
    if exchange == "sh" and code.startswith(("600", "601", "603", "605")):
        return "stock", "main"
    if exchange == "sz" and code.startswith(("000", "001", "003")):
        return "stock", "main"
    return "stock", "other"


def build_securities_staging(staging_dir: Path) -> int:
    """Infer securities metadata from the daily staging symbol universe."""
    daily = _read_staging_table(staging_dir, "daily")
    if daily.empty:
        raise ValueError("daily staging is empty")

    daily = daily[["symbol", "date"]].copy()
    daily["date"] = pd.to_datetime(daily["date"])
    grouped = daily.groupby("symbol", sort=True)["date"].agg(["min", "max"]).reset_index()

    calendar = pd.Index(sorted(daily["date"].dt.normalize().unique()))
    delist_cutoff = calendar[-21] if len(calendar) > 20 else calendar[0]

    classified = grouped["symbol"].map(_classify_security)
    securities = pd.DataFrame(
        {
            "symbol": grouped["symbol"].astype("string"),
            "code": grouped["symbol"].str[2:].astype("string"),
            "name": pd.NA,
            "exchange": grouped["symbol"].str[:2].astype("string"),
            "sec_type": [item[0] for item in classified],
            "board": [item[1] for item in classified],
            "list_date": grouped["min"].dt.date,
            "delist_date": grouped["max"].where(grouped["max"] < delist_cutoff).dt.date,
        }
    )
    _write_parquet(securities, staging_dir / "securities.parquet")
    return len(securities)


def build_blocks_staging(tdx_home_or_mirror: Path, staging_dir: Path) -> int:
    """Parse TDX block metadata, block members, and holidays into staging."""
    hq_cache = _resolve_hq_cache(tdx_home_or_mirror)

    block_rows: list[tuple] = []
    zs3 = hq_cache / "tdxzs3.cfg"
    if zs3.exists():
        block_rows = parse_tdxzs3(zs3)
    blocks = pd.DataFrame(
        block_rows,
        columns=[
            "block_type",
            "block_name",
            "block_symbol",
            "block_code",
            "parent_code",
            "block_level",
        ],
    )
    if not blocks.empty:
        blocks = (
            blocks.drop_duplicates("block_code").sort_values("block_code").reset_index(drop=True)
        )
        blocks["block_level"] = blocks["block_level"].astype("int16")

    member_rows: list[tuple[str, str]] = []
    infoharbor = hq_cache / "infoharbor_block.dat"
    if infoharbor.exists():
        member_rows.extend(parse_infoharbor_blocks(infoharbor))
    tdxhy = hq_cache / "tdxhy.cfg"
    if tdxhy.exists():
        member_rows.extend(parse_tdxhy(tdxhy))
    members = pd.DataFrame(member_rows, columns=["stock_symbol", "block_code"])
    if not members.empty:
        members = (
            members.drop_duplicates(["stock_symbol", "block_code"])
            .sort_values(["stock_symbol", "block_code"])
            .reset_index(drop=True)
        )

    holidays_path = hq_cache / "needini.dat"
    holidays = pd.DataFrame(
        {"date": parse_holidays(holidays_path) if holidays_path.exists() else []}
    )

    _write_parquet(blocks, staging_dir / "blocks.parquet")
    _write_parquet(members, staging_dir / "block_members.parquet")
    _write_parquet(holidays, staging_dir / "holidays.parquet")
    return len(blocks) + len(members) + len(holidays)


def _current_st_symbols(staging_dir: Path) -> set[str]:
    """Return snapshot ST/risk-warning members; not point-in-time."""
    blocks_path = staging_dir / "blocks.parquet"
    members_path = staging_dir / "block_members.parquet"
    if not blocks_path.exists() or not members_path.exists():
        return set()
    blocks = pd.read_parquet(blocks_path)
    members = pd.read_parquet(members_path)
    if blocks.empty or members.empty:
        return set()
    st_codes = blocks.loc[
        blocks["block_name"].astype(str).str.contains("ST|风险", case=False, regex=True),
        "block_code",
    ]
    return set(members.loc[members["block_code"].isin(st_codes), "stock_symbol"].astype(str))


def _round_price(values: pd.Series) -> pd.Series:
    return np.floor(values.astype("float64") * 100.0 + 0.5) / 100.0


def _limit_ratio(board: str, is_st: bool) -> float:
    if is_st:
        return 0.05
    if board in {"gem", "star"}:
        return 0.20
    if board == "bse":
        return 0.30
    return 0.10


def _build_symbol_flags(
    symbol: str,
    calendar: pd.Series,
    daily: pd.DataFrame,
    basics: pd.DataFrame,
    security: pd.Series,
    st_symbols: set[str],
) -> pd.DataFrame:
    list_date = pd.Timestamp(security["list_date"])
    raw_delist = security["delist_date"]
    end_date = pd.Timestamp(raw_delist) if pd.notna(raw_delist) else calendar.max()
    dates = calendar[(calendar >= list_date) & (calendar <= end_date)]

    frame = pd.DataFrame({"symbol": symbol, "date": dates})
    frame = frame.merge(daily, on=["symbol", "date"], how="left")
    frame = frame.merge(basics, on=["symbol", "date"], how="left")

    is_st = symbol in st_symbols
    board = str(security["board"])
    ratio = _limit_ratio(board, is_st)

    frame["is_suspended"] = frame["close"].isna()
    frame["is_st"] = is_st
    frame["limit_up_price"] = _round_price(frame["preclose"] * (1.0 + ratio))
    frame["limit_down_price"] = _round_price(frame["preclose"] * (1.0 - ratio))
    if board == "bse":
        first_day = frame["date"] == list_date
        frame.loc[first_day, ["limit_up_price", "limit_down_price"]] = np.nan

    close = _round_price(frame["close"])
    frame["is_limit_up"] = close.eq(frame["limit_up_price"]).fillna(False)
    frame["is_limit_down"] = close.eq(frame["limit_down_price"]).fillna(False)
    frame["date"] = frame["date"].dt.date
    return frame[
        [
            "symbol",
            "date",
            "is_suspended",
            "is_st",
            "limit_up_price",
            "limit_down_price",
            "is_limit_up",
            "is_limit_down",
        ]
    ]


def build_flags_staging(staging_dir: Path) -> int:
    """Build suspension/ST/limit flags from daily, securities, and basics staging.

    ST membership is a current snapshot from block metadata, not PIT history
    (same limitation as v1).
    """
    daily = _read_staging_table(staging_dir, "daily")[["symbol", "date", "close"]].copy()
    basics = _read_staging_table(staging_dir, "basics")[["symbol", "date", "preclose"]].copy()
    securities = _read_staging_table(staging_dir, "securities")

    daily["date"] = pd.to_datetime(daily["date"])
    basics["date"] = pd.to_datetime(basics["date"])
    securities["list_date"] = pd.to_datetime(securities["list_date"])
    securities["delist_date"] = pd.to_datetime(securities["delist_date"])

    calendar = pd.Series(sorted(daily["date"].dt.normalize().unique()))
    st_symbols = _current_st_symbols(staging_dir)
    daily_groups = {symbol: group for symbol, group in daily.groupby("symbol", sort=False)}
    basics_groups = {symbol: group for symbol, group in basics.groupby("symbol", sort=False)}

    out_path = staging_dir / "flags.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    rows = 0
    with pq.ParquetWriter(out_path, FLAGS_SCHEMA, compression="zstd") as writer:
        for security in securities.sort_values("symbol").itertuples(index=False):
            sec = pd.Series(security._asdict())
            symbol = str(sec["symbol"])
            frame = _build_symbol_flags(
                symbol,
                calendar,
                daily_groups.get(symbol, daily.iloc[:0]),
                basics_groups.get(symbol, basics.iloc[:0]),
                sec,
                st_symbols,
            )
            writer.write_table(
                pa.Table.from_pandas(frame, schema=FLAGS_SCHEMA, preserve_index=False)
            )
            rows += len(frame)
    return rows
