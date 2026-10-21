"""Incremental daily update helpers."""

from __future__ import annotations

import time
import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant.etl.adjust import compute_adjust
from quant.etl.basics import compute_basics
from quant.etl.qlib_dump import dump_cn_daily
from quant.etl.staging import RECORD_SIZE, build_flags_staging, parse_day_bytes
from quant.etl.tdx_parser import collect_day_files


@dataclass(frozen=True)
class UpdateStats:
    """Outcome of an incremental update."""

    new_rows: int
    symbols: int
    qlib_rebuilt: bool
    seconds: float


def _read_staging_table(staging_dir: Path, name: str) -> pd.DataFrame:
    directory = staging_dir / name
    if directory.exists():
        return pd.read_parquet(directory)
    file_path = staging_dir / f"{name}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    raise FileNotFoundError(f"missing staging table: {directory} or {file_path}")


def read_day_tail(path: Path, n_records: int) -> bytes:
    """Read the last ``n_records`` TDX .day records, or the whole short file."""
    if n_records <= 0:
        return b""
    size = path.stat().st_size
    n_bytes = n_records * RECORD_SIZE
    with path.open("rb") as fh:
        if size > n_bytes:
            fh.seek(-n_bytes, 2)
        return fh.read()


def collect_new_rows(tdx_home: Path, last_date: pd.Timestamp, *, margin: int = 5) -> pd.DataFrame:
    """Collect rows newer than ``last_date`` by tail-reading TDX day files."""
    last = pd.Timestamp(last_date).normalize()
    today = pd.Timestamp.today().normalize()
    n_records = max(int((today - last).days), 0) + margin
    frames: list[pd.DataFrame] = []
    for path, symbol in collect_day_files(tdx_home):
        df = parse_day_bytes(read_day_tail(path, n_records), symbol)
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["date"] > last]
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
        )
    return (
        pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)
    )


def _write_table(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression="zstd")


def _append_daily(staging_dir: Path, new_rows: pd.DataFrame) -> None:
    daily_dir = staging_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    max_date = pd.to_datetime(new_rows["date"]).max().date().isoformat()
    _write_table(daily_dir / f"update-{max_date}.parquet", new_rows)


def _replace_symbols(
    existing: pd.DataFrame, replacement: pd.DataFrame, symbols: set[str]
) -> pd.DataFrame:
    kept = existing[~existing["symbol"].isin(symbols)] if not existing.empty else existing
    return (
        pd.concat([kept, replacement], ignore_index=True)
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )


def _recompute_derived_for_symbols(
    staging_dir: Path, daily: pd.DataFrame, symbols: set[str]
) -> None:
    gbbq = _read_staging_table(staging_dir, "gbbq")
    affected_daily = daily[daily["symbol"].isin(symbols)].copy()

    basics_existing = _read_staging_table(staging_dir, "basics")
    adjust_existing = _read_staging_table(staging_dir, "adjust")
    basics_repl = compute_basics(affected_daily, gbbq)
    adjust_repl = compute_adjust(affected_daily, gbbq)
    _write_table(
        staging_dir / "basics.parquet", _replace_symbols(basics_existing, basics_repl, symbols)
    )
    _write_table(
        staging_dir / "adjust.parquet", _replace_symbols(adjust_existing, adjust_repl, symbols)
    )

    if (staging_dir / "flags.parquet").exists():
        build_flags_staging(staging_dir)


def apply_update(staging_dir: Path, qlib_dir: Path, new_rows: pd.DataFrame) -> UpdateStats:
    """Upsert an unsealed working staging tree, including corrected historical bars.

    Production publication is handled by ``quant.etl.restart``. Never mutate an
    immutable published snapshot through this legacy compatibility function.
    """
    if (staging_dir.parent / "manifest.json").exists():
        raise ValueError("sealed snapshot: build a new snapshot to update data")
    t0 = time.monotonic()
    incoming = new_rows.copy()
    if incoming.empty:
        return UpdateStats(new_rows=0, symbols=0, qlib_rebuilt=False, seconds=time.monotonic() - t0)

    incoming["date"] = pd.to_datetime(incoming["date"])
    daily = _read_staging_table(staging_dir, "daily").copy()
    daily["date"] = pd.to_datetime(daily["date"])
    columns = ["open", "high", "low", "close", "volume", "amount"]
    incoming = incoming.drop_duplicates(["symbol", "date"], keep="last")
    previous = daily.set_index(["symbol", "date"])[columns]
    candidate = incoming.set_index(["symbol", "date"])[columns]
    aligned = previous.reindex(candidate.index)
    unchanged = candidate.eq(aligned) | (candidate.isna() & aligned.isna())
    incoming = incoming.loc[~unchanged.all(axis=1).to_numpy()].copy()
    if incoming.empty:
        return UpdateStats(new_rows=0, symbols=0, qlib_rebuilt=False, seconds=time.monotonic() - t0)

    symbols = set(incoming["symbol"].astype(str))
    combined = (
        pd.concat([daily, incoming], ignore_index=True)
        .drop_duplicates(["symbol", "date"], keep="last")
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )
    # Replace the working table rather than append overlapping keys. The active
    # pointer never references this tree until the enclosing publisher seals it.
    daily_dir = staging_dir / "daily"
    temporary = staging_dir / "daily.upserting"
    temporary.mkdir(exist_ok=False)
    _write_table(
        temporary / "part-000.parquet",
        combined.assign(date=combined["date"].dt.date).drop(columns=["exchange"], errors="ignore"),
    )
    shutil.rmtree(daily_dir)
    temporary.rename(daily_dir)
    _recompute_derived_for_symbols(staging_dir, combined, symbols)
    dump_cn_daily(staging_dir, qlib_dir)
    return UpdateStats(
        new_rows=int(len(incoming)),
        symbols=len(symbols),
        qlib_rebuilt=True,
        seconds=time.monotonic() - t0,
    )
