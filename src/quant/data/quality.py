"""Bounded-memory whole-dataset checks and an explicit anomaly quarantine."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

OHLC = ["open", "high", "low", "close"]


def invalid_bars(frame: pd.DataFrame) -> pd.Series:
    """Identify structurally impossible bars, without filtering economic returns."""
    import numpy as np

    prices = frame[OHLC].astype(float)
    return (
        (~np.isfinite(prices)).any(axis=1)
        | prices.le(0).any(axis=1)
        | frame["high"].lt(prices[["open", "close", "low"]].max(axis=1))
        | frame["low"].gt(prices[["open", "close", "high"]].min(axis=1))
        | frame["volume"].lt(0)
        | frame["amount"].lt(0)
        | ~np.isfinite(frame["amount"].astype(float))
        | frame["date"].isna()
        | frame["symbol"].isna()
    )


def audit_daily(directory: Path) -> dict:
    """Scan all Parquet bars; distinguish validity from investment-grade evidence."""
    with duckdb.connect(":memory:") as con:
        con.read_parquet(str(directory / "**/*.parquet"), hive_partitioning=True).create_view(
            "bars"
        )
        row = con.sql("""
            SELECT count(*), count(DISTINCT symbol), min(date), max(date),
              count(*)-count(DISTINCT (symbol,date)),
              count(*) FILTER (WHERE symbol IS NULL OR date IS NULL OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL),
              count(*) FILTER (WHERE least(open,high,low,close)<=0
                OR NOT isfinite(open) OR NOT isfinite(high)
                OR NOT isfinite(low) OR NOT isfinite(close)),
              count(*) FILTER (WHERE high<greatest(open,close,low)
                OR low>least(open,close,high)),
              count(*) FILTER (WHERE volume IS NULL OR amount IS NULL OR volume<0 OR amount<0 OR NOT isfinite(amount))
            FROM bars
        """).fetchone()
        coverage = (
            con.sql("""
            SELECT symbol, min(date)::VARCHAR AS start, max(date)::VARCHAR AS end,
                   count(*) AS rows
            FROM bars GROUP BY symbol ORDER BY symbol
        """)
            .df()
            .to_dict("records")
        )
    names = [
        "rows",
        "symbols",
        "first_date",
        "last_date",
        "duplicate_keys",
        "null_keys_or_close",
        "invalid_prices",
        "invalid_ohlc",
        "invalid_activity",
    ]
    summary = dict(zip(names, row, strict=True))
    summary["first_date"] = str(summary["first_date"])
    summary["last_date"] = str(summary["last_date"])
    summary["structurally_valid"] = all(summary[key] == 0 for key in names[4:])
    return {"summary": summary, "coverage": coverage}
