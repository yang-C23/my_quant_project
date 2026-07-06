from __future__ import annotations

from typing import Iterable

import pandas as pd
import backtrader as bt

_DB_SCHEMA = "tdx"


def _get_db_connection():
    from quant.db.connection import get_connection

    return get_connection()


def load_symbol_db(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """Load OHLCV data from PostgreSQL.

    Args:
        symbol: Exchange-prefixed symbol (e.g. 'sz000001').
        start/end: Date strings for filtering.
        adjust: 'qfq' (forward), 'hfq' (backward), or 'bfq' (none).
    """
    view_map = {"qfq": "v_qfq_daily", "hfq": "v_hfq_daily", "bfq": "v_bfq_daily"}
    view = view_map.get(adjust, "v_qfq_daily")

    query = f"SELECT date, open, high, low, close, volume, amount FROM {_DB_SCHEMA}.{view} WHERE symbol = %s"
    params: list = [symbol]

    if start:
        query += " AND date >= %s"
        params.append(start)
    if end:
        query += " AND date <= %s"
        params.append(end)
    query += " ORDER BY date"

    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# Alias for unified interface
load_symbol = load_symbol_db


def list_symbols_from_db(
    sec_type: str = "stock",
    exclude_boards: set[str] | None = None,
) -> list[str]:
    """List all symbols from the securities master table."""
    query = f"SELECT symbol FROM {_DB_SCHEMA}.securities WHERE sec_type = %s"
    params: list = [sec_type]

    if exclude_boards:
        if "star" in exclude_boards:
            query += " AND board != 'star'"
        if "chinext" in exclude_boards or "gem" in exclude_boards:
            query += " AND board != 'chinext'"
        if "bse" in exclude_boards or "bj" in exclude_boards:
            query += " AND board != 'bse'"

    query += " ORDER BY symbol"

    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        symbols = [r[0] for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
    return symbols


class AStockPandasData(bt.feeds.PandasData):
    lines = ("is_suspended", "is_upper_limit", "is_lower_limit")
    params = (
        ("datetime", "date"),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", None),
        ("is_suspended", "is_suspended"),
        ("is_upper_limit", "is_upper_limit"),
        ("is_lower_limit", "is_lower_limit"),
    )


def build_data_feed(symbol: str, df: pd.DataFrame) -> bt.feeds.PandasData:
    df = df.copy()
    for col in ["is_suspended", "is_upper_limit", "is_lower_limit"]:
        if col not in df.columns:
            df[col] = 0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    data = AStockPandasData(dataname=df)
    data.plotinfo.plot = False
    data._name = symbol
    return data


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    out = []
    for sym in symbols:
        sym = str(sym).strip()
        if not sym:
            continue
        out.append(sym.zfill(6))
    return list(dict.fromkeys(out))


def filter_symbols_by_boards(symbols: Iterable[str], exclude_boards: set[str]) -> list[str]:
    if not exclude_boards:
        return normalize_symbols(symbols)

    filtered = []
    for sym in normalize_symbols(symbols):
        if "gem" in exclude_boards and sym.startswith(("300", "301")):
            continue
        if "star" in exclude_boards and sym.startswith("688"):
            continue
        if "bj" in exclude_boards and sym.startswith(("4", "8")):
            continue
        filtered.append(sym)
    return filtered
