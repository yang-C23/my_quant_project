"""Daily basic fields derived from raw bars and TDX GBBQ metadata."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quant.etl.adjust import daily_with_preclose

_SHARE_CATEGORIES = {2, 3, 5, 7, 8, 9, 10}


def _read_staging_table(staging_dir: Path, name: str) -> pd.DataFrame:
    directory = staging_dir / name
    if directory.exists():
        return pd.read_parquet(directory)
    file_path = staging_dir / f"{name}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    raise FileNotFoundError(f"missing staging table: {directory} or {file_path}")


def _shares_timeline(gbbq: pd.DataFrame) -> pd.DataFrame:
    if gbbq.empty:
        return pd.DataFrame(columns=["symbol", "date", "float_shares", "total_shares"])
    shares = gbbq.loc[
        gbbq["category"].isin(_SHARE_CATEGORIES), ["symbol", "date", "c3", "c4"]
    ].copy()
    if shares.empty:
        return pd.DataFrame(columns=["symbol", "date", "float_shares", "total_shares"])
    shares["date"] = pd.to_datetime(shares["date"])
    shares["float_shares"] = shares["c3"].astype(float) * 10_000.0
    shares["total_shares"] = shares["c4"].astype(float) * 10_000.0
    return shares[["symbol", "date", "float_shares", "total_shares"]].sort_values(
        ["symbol", "date"]
    )


def _attach_shares(daily: pd.DataFrame, gbbq: pd.DataFrame) -> pd.DataFrame:
    shares = _shares_timeline(gbbq)
    if shares.empty:
        daily = daily.copy()
        daily["float_shares"] = 0.0
        daily["total_shares"] = 0.0
        return daily

    parts: list[pd.DataFrame] = []
    for symbol, daily_part in daily.groupby("symbol", sort=False):
        share_part = shares.loc[
            shares["symbol"].eq(symbol), ["date", "float_shares", "total_shares"]
        ]
        if share_part.empty:
            enriched = daily_part.copy()
            enriched["float_shares"] = 0.0
            enriched["total_shares"] = 0.0
        else:
            enriched = pd.merge_asof(
                daily_part.sort_values("date"),
                share_part.sort_values("date"),
                on="date",
                direction="backward",
            )
            enriched[["float_shares", "total_shares"]] = enriched[
                ["float_shares", "total_shares"]
            ].fillna(0.0)
        parts.append(enriched)
    return pd.concat(parts, ignore_index=True)


def compute_basics(daily: pd.DataFrame, gbbq: pd.DataFrame) -> pd.DataFrame:
    """Compute daily preclose, returns, turnover, shares, and market caps."""
    required = {"symbol", "date", "open", "high", "low", "close", "volume", "amount"}
    missing = required - set(daily.columns)
    if missing:
        raise KeyError(f"daily missing required columns: {sorted(missing)}")

    frame = daily_with_preclose(daily, gbbq)
    frame["pct_chg"] = np.where(
        frame["preclose"].gt(0),
        ((frame["close"] - frame["preclose"]) / frame["preclose"] * 100.0).round(2),
        0.0,
    )
    frame["amplitude"] = np.where(
        frame["preclose"].gt(0),
        ((frame["high"] - frame["low"]) / frame["preclose"] * 100.0).round(2),
        0.0,
    )
    frame = _attach_shares(frame, gbbq)
    frame["turnover"] = np.where(
        frame["float_shares"].gt(0),
        (frame["volume"].astype(float) / frame["float_shares"]).round(6),
        0.0,
    )
    frame["float_mktcap"] = (frame["float_shares"] * frame["close"].astype(float)).round(2)
    frame["total_mktcap"] = (frame["total_shares"] * frame["close"].astype(float)).round(2)
    frame["date"] = frame["date"].dt.date
    return frame[
        [
            "symbol",
            "date",
            "preclose",
            "pct_chg",
            "amplitude",
            "turnover",
            "float_shares",
            "total_shares",
            "float_mktcap",
            "total_mktcap",
        ]
    ]


def build_basics_staging(staging_dir: Path) -> int:
    """Build ``staging/basics.parquet`` from daily and gbbq staging tables."""
    daily = _read_staging_table(staging_dir, "daily")
    gbbq = _read_staging_table(staging_dir, "gbbq")
    basics = compute_basics(daily, gbbq)
    basics.to_parquet(staging_dir / "basics.parquet", index=False, compression="zstd")
    return len(basics)
