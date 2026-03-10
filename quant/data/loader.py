from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
import backtrader as bt

# ── PostgreSQL data loading ───────────────────────────────────────────────────

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


def load_symbol(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    adjust: str = "qfq",
    source: str = "db",
    data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Unified loader: reads from DB (default) or CSV fallback.

    Args:
        source: 'db' for PostgreSQL, 'csv' for legacy CSV files.
        data_dir: Required when source='csv'.
    """
    if source == "db":
        return load_symbol_db(symbol, start=start, end=end, adjust=adjust)
    if data_dir is None:
        raise ValueError("data_dir is required when source='csv'")
    return load_symbol_csv(symbol, data_dir=data_dir, start=start, end=end)


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


def _resolve_dirs(data_dir: str | Path) -> tuple[Path, Path, Path]:
    base = Path(data_dir)
    raw_dir = base / "raw_price"
    factor_dir = base / "adj_factor"
    adj_dir = base / "adj_price"
    return raw_dir, factor_dir, adj_dir


def _load_raw_price(symbol: str, data_dir: str | Path) -> pd.DataFrame:
    raw_dir, _, _ = _resolve_dirs(data_dir)
    path = raw_dir / f"{symbol}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Raw data file not found: {path}")

    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError(f"Missing 'date' column in {path}")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_adj_factor(symbol: str, data_dir: str | Path) -> pd.DataFrame:
    _, factor_dir, _ = _resolve_dirs(data_dir)
    path = factor_dir / f"{symbol}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Adj factor file not found: {path}")

    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError(f"Missing 'date' column in {path}")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if "factor" not in df.columns:
        raise ValueError(f"Missing 'factor' column in {path}")
    df["factor"] = pd.to_numeric(df["factor"], errors="coerce")
    return df


def load_symbol_csv(
    symbol: str,
    data_dir: str | Path,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    try:
        df = _load_adj_price(symbol, data_dir=data_dir)
        source = "adj_price"
    except FileNotFoundError:
        df = pd.DataFrame()
        source = "raw_factor"

    if df.empty and source == "raw_factor":
        raw_df = _load_raw_price(symbol, data_dir=data_dir)
        factor_df = _load_adj_factor(symbol, data_dir=data_dir)

        df = pd.merge(raw_df, factor_df, on="date", how="left")
        df["factor"] = df["factor"].ffill().bfill()
        df = df.dropna(subset=["open", "high", "low", "close", "factor"])

        if df.empty:
            return df

        last_factor = df["factor"].iloc[-1]
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] * last_factor / df["factor"]
        df = df.drop(columns=["factor"]).reset_index(drop=True)

    if start:
        start_dt = pd.to_datetime(start)
        df = df[df["date"] >= start_dt]
    if end:
        end_dt = pd.to_datetime(end)
        df = df[df["date"] <= end_dt]

    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return df


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


def list_symbols_from_data_dir(data_dir: str | Path) -> list[str]:
    raw_dir, _, adj_dir = _resolve_dirs(data_dir)
    search_dir = adj_dir if adj_dir.exists() else raw_dir
    if not search_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {search_dir}")
    symbols = [p.stem for p in search_dir.glob("*.csv") if p.is_file()]
    return sorted(symbols)


def load_symbols_from_stocklist(stocklist_path: str | Path, limit: int = 0) -> list[str]:
    stocklist = Path(stocklist_path)
    if not stocklist.exists():
        raise FileNotFoundError(f"Stocklist not found: {stocklist}")

    df = pd.read_csv(stocklist)
    if "symbol" in df.columns:
        symbols = df["symbol"].astype(str).str.zfill(6)
    elif "ts_code" in df.columns:
        symbols = df["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    else:
        raise ValueError("stocklist.csv must contain 'symbol' or 'ts_code' column")

    symbols = list(dict.fromkeys(symbols.tolist()))
    if limit > 0:
        symbols = symbols[:limit]
    return symbols


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
def _load_adj_price(symbol: str, data_dir: str | Path) -> pd.DataFrame:
    _, _, adj_dir = _resolve_dirs(data_dir)
    path = adj_dir / f"{symbol}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Adj price file not found: {path}")

    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError(f"Missing 'date' column in {path}")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
