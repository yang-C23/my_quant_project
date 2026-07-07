"""Dual trend and volume breath indicators."""

from __future__ import annotations

import pandas as pd

from quant.indicators.kdj import kdj
from quant.tdx import functions as F

_LOW_SENTINEL = 99_999_999.0


def _require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"missing required columns: {missing}")


def _rolling_tdx_volume_breath(volume: pd.Series, n: int) -> pd.DataFrame:
    """Vectorized literal TDX ``HHV(IF(...))`` volume-breath extrema."""
    if n <= 0:
        raise ValueError(f"n_vol must be positive, got {n}")

    v = volume.astype(float)
    vh1 = v.rolling(n).max()
    vh2 = v.where(v < vh1, 0.0).rolling(n).max()
    vh3 = v.where(v < vh2, 0.0).rolling(n).max()
    vl1 = v.rolling(n).min()
    vl2 = v.where(v > vl1, _LOW_SENTINEL).rolling(n).min()
    vl3 = v.where(v > vl2, _LOW_SENTINEL).rolling(n).min()
    return pd.DataFrame(
        {
            "avghigh": (vh1 + vh2 + vh3) / 3.0,
            "avglow": (vl1 + vl2 + vl3) / 3.0,
            "vh1": vh1,
            "vl1": vl1,
        },
        index=volume.index,
    )


def dual_trend(
    df: pd.DataFrame,
    *,
    n1: int = 10,
    m: tuple[int, int, int, int] = (14, 28, 57, 114),
    n_vol: int = 30,
    vol_ratio: float = 3.5,
    j_low: float = 13.0,
) -> pd.DataFrame:
    """Return dual-trend, KDJ, volume-breath, and signal columns for one symbol."""
    if n1 <= 0:
        raise ValueError(f"n1 must be positive, got {n1}")
    if len(m) != 4 or any(period <= 0 for period in m):
        raise ValueError(f"m must contain four positive periods, got {m}")
    _require_columns(df, ("close", "high", "low", "volume"))

    close = df["close"].astype(float)
    white = F.EMA(F.EMA(close, n1), n1)
    yellow = sum(F.MA(close, period) for period in m) / 4.0

    kdj_frame = kdj(df)
    breath = _rolling_tdx_volume_breath(df["volume"], n_vol)
    breath_active = breath["avghigh"] > vol_ratio * breath["avglow"]
    zone_ok = (close < white) & (close > yellow)
    trend_ok = white > yellow

    sig_dual_trend_entry = trend_ok & breath_active & (kdj_frame["j"] < j_low) & zone_ok
    sig_golden_cross = F.CROSS(white, yellow)
    sig_dead_cross = F.CROSS(yellow, white)

    return pd.DataFrame(
        {
            "white": white,
            "yellow": yellow,
            "j": kdj_frame["j"],
            "avghigh": breath["avghigh"],
            "avglow": breath["avglow"],
            "breath_active": breath_active.fillna(False).astype(bool),
            "zone_ok": zone_ok.fillna(False).astype(bool),
            "sig_dual_trend_entry": sig_dual_trend_entry.fillna(False).astype(bool),
            "sig_golden_cross": sig_golden_cross.astype(bool),
            "sig_dead_cross": sig_dead_cross.astype(bool),
        },
        index=df.index,
    )
