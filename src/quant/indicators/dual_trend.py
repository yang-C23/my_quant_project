"""Dual trend and volume breath indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from quant.indicators.kdj import kdj
from quant.tdx import functions as F

_LOW_SENTINEL = 99_999_999.0


def _require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"missing required columns: {missing}")


def _rolling_distinct_volume_breath(volume: pd.Series, n: int) -> pd.DataFrame:
    """Vectorized TDX ``HHV(IF(...))`` volume-breath extrema.

    The formula uses strict ``<`` / ``>`` when selecting the next high/low,
    so repeated volume values count once for the top/bottom-three average.
    """
    if n <= 0:
        raise ValueError(f"n_vol must be positive, got {n}")

    values = volume.astype(float).to_numpy()
    out = np.full((len(values), 4), np.nan, dtype=float)
    if len(values) < n:
        return pd.DataFrame(out, columns=["avghigh", "avglow", "vh1", "vl1"], index=volume.index)

    windows = sliding_window_view(values, n)
    valid = ~np.isnan(windows).any(axis=1)
    if valid.any():
        valid_windows = windows[valid]

        vh1 = valid_windows.max(axis=1)
        vh2 = np.where(valid_windows < vh1[:, None], valid_windows, 0.0).max(axis=1)
        vh3 = np.where(valid_windows < vh2[:, None], valid_windows, 0.0).max(axis=1)

        vl1 = valid_windows.min(axis=1)
        vl2 = np.where(valid_windows > vl1[:, None], valid_windows, _LOW_SENTINEL).min(axis=1)
        vl3 = np.where(valid_windows > vl2[:, None], valid_windows, _LOW_SENTINEL).min(axis=1)

        rows = np.column_stack(
            [
                (vh1 + vh2 + vh3) / 3.0,
                (vl1 + vl2 + vl3) / 3.0,
                vh1,
                vl1,
            ]
        )
        out[np.flatnonzero(valid) + n - 1] = rows

    return pd.DataFrame(out, columns=["avghigh", "avglow", "vh1", "vl1"], index=volume.index)


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
    breath = _rolling_distinct_volume_breath(df["volume"], n_vol)
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
