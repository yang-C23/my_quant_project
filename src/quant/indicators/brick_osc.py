"""Brick oscillator and the three stock-picking variants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from quant.indicators.kdj import kdj
from quant.tdx import functions as F


@dataclass(frozen=True)
class BrickParams:
    """Parameters that differ between the brick stock-picking variants."""

    signal_col: Literal["sig_brick_strict", "sig_brick_relaxed", "sig_brick_len"]
    require_burst: bool
    oversold_mode: Literal["none", "prev", "recent3"]
    require_len_check: bool
    smallup_pct: float
    strong_ratio: float = 0.67
    burst_ratio: float = 0.80
    len_ratio: float = 0.35
    j_max: float = 13.0


PRESETS: dict[str, BrickParams] = {
    "strict": BrickParams(
        signal_col="sig_brick_strict",
        require_burst=True,
        oversold_mode="none",
        require_len_check=False,
        smallup_pct=0.03,
    ),
    "relaxed": BrickParams(
        signal_col="sig_brick_relaxed",
        require_burst=False,
        oversold_mode="prev",
        require_len_check=False,
        smallup_pct=0.03,
    ),
    "len_checked": BrickParams(
        signal_col="sig_brick_len",
        require_burst=False,
        oversold_mode="recent3",
        require_len_check=True,
        smallup_pct=0.04,
    ),
}


def _require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"missing required columns: {missing}")


def _compose_brick_signal(
    zxt: pd.Series,
    brick_delta: pd.Series,
    close: pd.Series,
    trend: pd.Series,
    j: pd.Series,
    params: BrickParams,
) -> pd.DataFrame:
    prev_delta = F.REF(brick_delta, 1)
    turn = (prev_delta <= 0) & (brick_delta > 0)
    strong = brick_delta >= params.strong_ratio * prev_delta.abs()
    smallup = (close > F.REF(close, 1)) & ((close / F.REF(close, 1) - 1.0) <= params.smallup_pct)
    burst = (brick_delta >= params.burst_ratio * F.HHV(brick_delta.abs(), 6)) & (zxt > 0)

    abs_delta_hhv = F.HHV(brick_delta.abs(), 6)
    gok = prev_delta.abs() >= params.len_ratio * abs_delta_hhv
    rok = brick_delta >= params.len_ratio * abs_delta_hhv

    if params.oversold_mode == "none":
        oversold = pd.Series(True, index=close.index)
    elif params.oversold_mode == "prev":
        oversold = F.REF(j, 1) < params.j_max
    else:
        oversold = F.EXIST(F.REF(j, 1) < params.j_max, 3)

    sig = turn & strong & smallup & trend
    if params.require_burst:
        sig &= burst
    if params.oversold_mode != "none":
        sig &= oversold
    if params.require_len_check:
        sig &= gok & rok

    return pd.DataFrame(
        {
            "sig_brick_turn": turn.fillna(False).astype(bool),
            "brick_strong": strong.fillna(False).astype(bool),
            "brick_smallup": smallup.fillna(False).astype(bool),
            "brick_burst": burst.fillna(False).astype(bool),
            "brick_gok": gok.fillna(False).astype(bool),
            "brick_rok": rok.fillna(False).astype(bool),
            "brick_oversold": oversold.fillna(False).astype(bool),
            params.signal_col: sig.fillna(False).astype(bool),
        },
        index=close.index,
    )


def brick_osc(df: pd.DataFrame, params: BrickParams = PRESETS["strict"]) -> pd.DataFrame:
    """Return brick oscillator columns and one selected variant signal."""
    _require_columns(df, ("high", "low", "close"))
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    high4 = F.HHV(high, 4)
    low4 = F.LLV(low, 4)
    denom = high4 - low4
    var1a = F.IIF(denom == 0, 0.0, (high4 - close) / denom * 100.0 - 90.0)
    var2a = F.SMA(var1a, 4, 1) + 100.0
    var3a = F.IIF(denom == 0, 0.0, (close - low4) / denom * 100.0)
    var4a = F.SMA(var3a, 6, 1)
    var5a = F.SMA(var4a, 6, 1) + 100.0
    var6a = var5a - var2a
    zxt = (var6a - 4.0).where(var6a > 4.0, 0.0).where(var6a.notna())
    brick_delta = zxt - F.REF(zxt, 1)

    zx_short = F.EMA(F.EMA(close, 10), 10)
    zx_bullbear = (F.MA(close, 14) + F.MA(close, 28) + F.MA(close, 57) + F.MA(close, 114)) / 4.0
    trend = zx_short > zx_bullbear
    signal = _compose_brick_signal(zxt, brick_delta, close, trend, kdj(df)["j"], params)

    return pd.concat(
        [
            pd.DataFrame(
                {
                    "zxt": zxt,
                    "brick_delta": brick_delta,
                    "zx_short": zx_short,
                    "zx_bullbear": zx_bullbear,
                },
                index=df.index,
            ),
            signal,
        ],
        axis=1,
    )
