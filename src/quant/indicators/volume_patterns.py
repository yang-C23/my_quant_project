"""Volume-pattern indicators from the research notes."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.tdx import functions as F


def _require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"missing required columns: {missing}")


def _real_yin(open_: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = F.REF(close, 1)
    return (close < open_) & ~(close > prev_close)


def volume_patterns(
    df: pd.DataFrame, *, dv_ratio: float = 2.0, half_ratio: float = 0.5, dead_window: int = 60
) -> pd.DataFrame:
    """Return double-volume, pullback, and washout-pattern columns.

    Signals are emitted on the pattern completion bar. ``sig_dvy_sandwich``
    requires a double-volume positive candle, two or three shrinking pullback
    bars, then a final double-volume positive candle.
    """
    _require_columns(df, ("open", "high", "low", "close", "volume"))
    open_ = df["open"].astype(float)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)
    prev_close = F.REF(close, 1)
    prev_volume = F.REF(volume, 1)

    double_volume = (prev_volume > 0) & (volume >= dv_ratio * prev_volume)
    double_vol_yang = double_volume & (close > open_)
    pullback = (close < prev_close) & (volume < prev_volume)
    sandwich_2 = (
        double_vol_yang.shift(3, fill_value=False)
        & pullback.shift(2, fill_value=False)
        & pullback.shift(1, fill_value=False)
    )
    sandwich_3 = (
        double_vol_yang.shift(4, fill_value=False)
        & pullback.shift(3, fill_value=False)
        & pullback.shift(2, fill_value=False)
        & pullback.shift(1, fill_value=False)
    )
    dvy_sandwich = double_vol_yang & (sandwich_2 | sandwich_3)

    price_up = close > prev_close
    volume_up = volume > prev_volume
    dvy_price_up = double_vol_yang & price_up & volume_up
    triple_dvy = (
        dvy_price_up
        & dvy_price_up.shift(1, fill_value=False)
        & dvy_price_up.shift(2, fill_value=False)
    )

    real_yin = _real_yin(open_, close)
    half_down = (
        ~real_yin.shift(1, fill_value=False)
        & (close < prev_close)
        & (volume <= half_ratio * prev_volume)
    )
    dead_vol = volume <= F.LLV(volume, dead_window) * 1.1

    high_zone = close >= 0.85 * F.HHV(close, dead_window)
    dvy_distribution = double_volume & real_yin & high_zone
    green_area = F.SUM(volume.where(close < open_, 0.0), dead_window)
    red_area = F.SUM(volume.where(close >= open_, 0.0), dead_window)
    washout_area_ratio = (green_area / red_area).where(red_area != 0)

    return pd.DataFrame(
        {
            "sig_double_vol_yang": double_vol_yang.fillna(False).astype(bool),
            "sig_dvy_sandwich": dvy_sandwich.fillna(False).astype(bool),
            "sig_triple_dvy": triple_dvy.fillna(False).astype(bool),
            "sig_half_down": half_down.fillna(False).astype(bool),
            "sig_dead_vol": dead_vol.fillna(False).astype(bool),
            "sig_dvy_distribution": dvy_distribution.fillna(False).astype(bool),
            "washout_area_ratio": washout_area_ratio.replace([np.inf, -np.inf], np.nan),
        },
        index=df.index,
    )


def single_needle_proxy(
    df: pd.DataFrame,
    *,
    shrink_ratio: float = 0.5,
    shadow_body_ratio: float = 2.0,
    dip_pct: float = 0.03,
) -> pd.DataFrame:
    """Return the proxy single-needle signal.

    This is a shape-only proxy, not equivalent to the original Compass
    (ZhiNanZhen) proprietary capital-line signal from the notes. The notes' prior is
    roughly 37% win rate and 3:1 payoff; that remains a research benchmark,
    not a claim of parity for this proxy.
    """
    _require_columns(df, ("open", "high", "low", "close", "volume"))
    open_ = df["open"].astype(float)
    close = df["close"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    prev_close = F.REF(close, 1)
    prev_volume = F.REF(volume, 1)

    bbi = (F.MA(close, 3) + F.MA(close, 6) + F.MA(close, 12) + F.MA(close, 24)) / 4.0
    lower_shadow = np.minimum(open_, close) - low
    body = (close - open_).abs()
    lower_shadow_ok = lower_shadow >= shadow_body_ratio * body
    deep_dip = (prev_close - low) / prev_close >= dip_pct
    recovered = close > low
    shrink = volume <= shrink_ratio * prev_volume
    n_low_held = low >= F.REF(F.LLV(low, 20), 1)
    sig = (close >= bbi) & lower_shadow_ok & deep_dip & recovered & shrink & n_low_held

    return pd.DataFrame({"sig_single_needle": sig.fillna(False).astype(bool)}, index=df.index)
