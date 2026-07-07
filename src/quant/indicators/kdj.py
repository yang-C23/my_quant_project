"""KDJ indicator with TDX SMA semantics."""

from __future__ import annotations

import pandas as pd

from quant.tdx import functions as F


def _require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"missing required columns: {missing}")


def kdj(df: pd.DataFrame, *, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """Return TDX-style KDJ columns ``k``, ``d``, and ``j`` for one symbol.

    Input must be sorted by date and contain ``high``, ``low``, and ``close``.
    ``SMA`` uses TDX recursion semantics from :mod:`quant.tdx.functions`.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    _require_columns(df, ("high", "low", "close"))

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    low_n = F.LLV(low, n)
    high_n = F.HHV(high, n)
    denom = high_n - low_n
    rsv = ((close - low_n) / denom * 100.0).where(denom != 0)
    k = F.SMA(rsv, m1, 1)
    d = F.SMA(k, m2, 1)
    j = 3.0 * k - 2.0 * d
    return pd.DataFrame({"k": k, "d": d, "j": j}, index=df.index)
