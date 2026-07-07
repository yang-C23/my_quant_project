"""Dump staging parquet tables into qlib cn_daily binary layout."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from quant.etl._qlib_dump_vendor import write_feature_bin


@dataclass
class DumpStats:
    """Outcome of a qlib dump."""

    instruments: int
    rows: int
    fields: int
    seconds: float


_FIELD_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "factor",
    "amount",
    "turnover",
    "float_mktcap",
    "total_mktcap",
    "st",
    "suspended",
    "limit_up",
    "limit_down",
    "limit_up_price",
    "limit_down_price",
]


def _read_staging_table(staging_dir: Path, name: str) -> pd.DataFrame:
    directory = staging_dir / name
    if directory.exists():
        return pd.read_parquet(directory)
    file_path = staging_dir / f"{name}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    raise FileNotFoundError(f"missing staging table: {directory} or {file_path}")


def _read_optional_staging_table(staging_dir: Path, name: str) -> pd.DataFrame:
    try:
        return _read_staging_table(staging_dir, name)
    except FileNotFoundError:
        return pd.DataFrame()


def _to_qlib_symbol(symbol: str) -> str:
    return symbol[:2].upper() + symbol[2:]


def build_calendar(staging_dir: Path) -> list[pd.Timestamp]:
    """Return the sorted daily calendar from staging daily bars."""
    daily = _read_staging_table(staging_dir, "daily")[["date"]]
    return list(pd.to_datetime(daily["date"]).drop_duplicates().sort_values())


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def build_instruments(staging_dir: Path, out_dir: Path) -> None:
    """Write qlib instruments files: all, nostar, stocks_nostar, and main_only."""
    securities = _read_staging_table(staging_dir, "securities").copy()
    securities["list_date"] = pd.to_datetime(securities["list_date"])
    securities["delist_date"] = pd.to_datetime(securities["delist_date"])
    calendar = build_calendar(staging_dir)
    calendar_end = calendar[-1]
    securities["end_date"] = securities["delist_date"].fillna(calendar_end)

    def lines_for(frame: pd.DataFrame) -> list[str]:
        rows = []
        for row in frame.sort_values("symbol").itertuples(index=False):
            rows.append(
                f"{_to_qlib_symbol(row.symbol)}\t"
                f"{pd.Timestamp(row.list_date).date().isoformat()}\t"
                f"{pd.Timestamp(row.end_date).date().isoformat()}\n"
            )
        return rows

    inst_dir = out_dir / "instruments"
    _write_lines(inst_dir / "all.txt", lines_for(securities))
    _write_lines(inst_dir / "nostar.txt", lines_for(securities[~securities["board"].eq("star")]))
    stocks = securities[securities["sec_type"].eq("stock")]
    _write_lines(
        inst_dir / "stocks_nostar.txt",
        lines_for(stocks[~stocks["board"].isin({"star", "b"})]),
    )
    _write_lines(
        inst_dir / "main_only.txt",
        lines_for(securities[securities["sec_type"].eq("stock") & securities["board"].eq("main")]),
    )


def _prepare_features(staging_dir: Path, symbols: set[str] | None = None) -> pd.DataFrame:
    daily = _read_staging_table(staging_dir, "daily").copy()
    adjust = _read_staging_table(staging_dir, "adjust").copy()
    basics = _read_staging_table(staging_dir, "basics").copy()
    flags = _read_optional_staging_table(staging_dir, "flags").copy()

    for frame in (daily, adjust, basics, flags):
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"])
            if symbols is not None and "symbol" in frame.columns:
                frame.drop(frame.loc[~frame["symbol"].isin(symbols)].index, inplace=True)

    base = daily.merge(adjust, on=["symbol", "date"], how="left").merge(
        basics, on=["symbol", "date"], how="left"
    )
    if not flags.empty:
        base = base.merge(flags, on=["symbol", "date"], how="outer")

    factor = base["hfq_factor"].astype(float)
    for col in ("open", "high", "low", "close"):
        base[col] = base[col].astype(float) * factor
    base["volume"] = base["volume"].astype(float) / factor
    base["factor"] = factor

    def bool_feature(column: str) -> pd.Series:
        if column not in base.columns:
            return pd.Series(False, index=base.index, dtype=bool)
        return base[column].astype("boolean").fillna(False).astype(bool)

    base["st"] = bool_feature("is_st").astype(float)
    base["suspended"] = bool_feature("is_suspended").astype(float)
    base["limit_up"] = bool_feature("is_limit_up").astype(float)
    base["limit_down"] = bool_feature("is_limit_down").astype(float)
    for col in _FIELD_COLUMNS:
        if col not in base.columns:
            base[col] = np.nan
    return base.sort_values(["symbol", "date"]).reset_index(drop=True)


def _write_calendar(calendar: list[pd.Timestamp], qlib_dir: Path) -> None:
    lines = [f"{pd.Timestamp(dt).date().isoformat()}\n" for dt in calendar]
    _write_lines(qlib_dir / "calendars" / "day.txt", lines)


def _dump_feature_group(
    group: pd.DataFrame, calendar_index: dict[pd.Timestamp, int], qlib_dir: Path
) -> int:
    symbol = str(group["symbol"].iloc[0])
    qlib_symbol = _to_qlib_symbol(symbol)
    dates = pd.to_datetime(group["date"])
    indexes = dates.map(calendar_index).astype(int).to_numpy()
    start_idx = int(indexes.min())
    end_idx = int(indexes.max())
    length = end_idx - start_idx + 1

    for field in _FIELD_COLUMNS:
        values = np.full(length, np.nan, dtype=np.float32)
        values[indexes - start_idx] = group[field].astype("float32").to_numpy()
        write_feature_bin(
            qlib_dir / "features" / qlib_symbol.lower() / f"{field}.day.bin", values, start_idx
        )
    return len(group)


def dump_cn_daily(staging_dir: Path, qlib_dir: Path, symbols: list[str] | None = None) -> DumpStats:
    """Rebuild a qlib cn_daily directory from staging parquet tables."""
    t0 = time.monotonic()
    if qlib_dir.exists():
        shutil.rmtree(qlib_dir)
    qlib_dir.mkdir(parents=True, exist_ok=True)

    calendar = build_calendar(staging_dir)
    calendar_index = {pd.Timestamp(dt): i for i, dt in enumerate(calendar)}
    _write_calendar(calendar, qlib_dir)
    build_instruments(staging_dir, qlib_dir)

    symbol_set = set(symbols) if symbols else None
    features = _prepare_features(staging_dir, symbol_set)
    rows = 0
    for _, group in features.groupby("symbol", sort=True):
        rows += _dump_feature_group(group, calendar_index, qlib_dir)
    seconds = time.monotonic() - t0
    return DumpStats(
        instruments=int(features["symbol"].nunique()),
        rows=rows,
        fields=len(_FIELD_COLUMNS),
        seconds=seconds,
    )
