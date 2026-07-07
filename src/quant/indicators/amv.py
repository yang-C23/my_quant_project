"""Active Market Value (0AMV) timing indicator."""

from __future__ import annotations

import pandas as pd

from quant.tdx import functions as F


def _require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"missing required columns: {missing}")


def amv(df: pd.DataFrame, *, n: int = 10, k: float = 2.13) -> pd.DataFrame:
    """Build the 0AMV pseudo-OHLC series for an index daily frame."""
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    _require_columns(df, ("open", "high", "low", "close", "amount"))

    amount = df["amount"].astype(float)
    close = df["close"].astype(float)
    amount_smooth = F.SMA(amount, n, 1) / 1_000_000.0
    prev_close_ma5 = F.MA(F.REF(close, 1), 5)
    scale = amount_smooth / prev_close_ma5 * 0.1 * k

    amv_open = scale * df["open"].astype(float)
    amv_high = scale * df["high"].astype(float)
    amv_low = scale * df["low"].astype(float)
    amv_close = scale * close

    amv_prev_close = F.REF(amv_close, 1)
    amv_pct = ((amv_close - amv_prev_close) / amv_prev_close * 100.0).where(amv_prev_close != 0)
    amv_life = F.EMA(amv_close, 12)

    return pd.DataFrame(
        {
            "amv_open": amv_open,
            "amv_high": amv_high,
            "amv_low": amv_low,
            "amv_close": amv_close,
            "amv_pct": amv_pct,
            "amv_life": amv_life,
        },
        index=df.index,
    )


def amv_timing_signal(
    amv_df: pd.DataFrame, *, buy_th: float = 4.0, sell_th: float = -2.3
) -> pd.DataFrame:
    """Return AMV buy/sell triggers and the derived holding regime."""
    _require_columns(amv_df, ("amv_pct",))

    pct = amv_df["amv_pct"].astype(float)
    sig_buy = ((pct >= buy_th) | ((pct + pct.shift(1)) >= buy_th)).fillna(False)
    sig_sell = (pct <= sell_th).fillna(False)

    regime: list[int] = []
    holding = 0
    for buy, sell in zip(sig_buy, sig_sell, strict=True):
        if sell:
            holding = 0
        elif buy:
            holding = 1
        regime.append(holding)

    return pd.DataFrame(
        {
            "sig_amv_buy": sig_buy.astype(bool),
            "sig_amv_sell": sig_sell.astype(bool),
            "regime": pd.Series(regime, index=amv_df.index, dtype="int8"),
        },
        index=amv_df.index,
    )
