"""B1 stock-picking indicator, parameterized across v2.42 variants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from quant.indicators.kdj import kdj
from quant.tdx import functions as F


@dataclass(frozen=True)
class B1Params:
    """Parameters that differ between B1 v2.42 variants."""

    yangyin_windows: tuple[tuple[int, float], ...]
    yangyin_mode: Literal["and3", "or2"]
    cnt_bad_window: int
    plry_long_count: int
    three_sum_window: int
    three_sum_min: int
    maxvol_window: int
    line_mult: float
    j_max: float = 13.0


PRESETS: dict[str, B1Params] = {
    "b1_v242_62": B1Params(
        yangyin_windows=((28, 1.4), (14, 2.0), (57, 1.2)),
        yangyin_mode="and3",
        cnt_bad_window=14,
        plry_long_count=3,
        three_sum_window=28,
        three_sum_min=2,
        maxvol_window=14,
        line_mult=0.995,
    ),
    "b1_v242b": B1Params(
        yangyin_windows=((57, 1.25), (14, 2.25)),
        yangyin_mode="or2",
        cnt_bad_window=21,
        plry_long_count=4,
        three_sum_window=57,
        three_sum_min=4,
        maxvol_window=28,
        line_mult=0.985,
    ),
    "b1_v242p": B1Params(
        yangyin_windows=((28, 2.25), (14, 2.75)),
        yangyin_mode="or2",
        cnt_bad_window=21,
        plry_long_count=4,
        three_sum_window=28,
        three_sum_min=3,
        maxvol_window=14,
        line_mult=0.985,
    ),
}


def _require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"missing required columns: {missing}")


def _bool_ref(x: pd.Series, n: int = 1) -> pd.Series:
    return x.shift(n, fill_value=False).astype(bool)


def _yangyin_ok(
    volume: pd.Series, real_yang: pd.Series, real_yin: pd.Series, window: int, mult: float
) -> pd.Series:
    vol_yang = F.SUM(volume * real_yang.astype(float), window)
    vol_yin = F.SUM(volume * real_yin.astype(float), window)
    return (vol_yang > mult * vol_yin).fillna(False)


def _hm_long(close: pd.Series) -> pd.Series:
    first = (
        0.2 * F.MA(close, 12)
        + 0.3 * F.MA(close, 24)
        + 0.3 * F.MA(close, 52)
        + 0.2 * F.MA(close, 108)
    )
    second = (
        0.4 * F.MA(close, 20)
        + 0.25 * F.MA(close, 40)
        + 0.25 * F.MA(close, 80)
        + 0.1 * F.MA(close, 160)
    )
    return 0.5 * first + 0.5 * second


def b1(df: pd.DataFrame, params: B1Params = PRESETS["b1_v242_62"]) -> pd.DataFrame:
    """Return B1 component columns and ``sig_b1`` for one symbol.

    Market-cap filtering (MVOK) and board exclusions are intentionally not
    applied here; they belong to the signals/universe layer.
    """
    _require_columns(df, ("open", "high", "low", "close", "volume"))
    open_ = df["open"].astype(float)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)
    prev_close = F.REF(close, 1)

    real_yang = (close > open_) & ~(close < prev_close)
    real_yin = (close < open_) & ~(close > prev_close)
    j = kdj(df)["j"]
    j_ok = j <= params.j_max

    yangyin_cols: dict[str, pd.Series] = {}
    for idx, (window, mult) in enumerate(params.yangyin_windows, start=1):
        yangyin_cols[f"yangyin_ok{idx}"] = _yangyin_ok(volume, real_yang, real_yin, window, mult)
    yangyin_ok1 = yangyin_cols["yangyin_ok1"]
    yangyin_ok2 = yangyin_cols["yangyin_ok2"]
    yangyin_ok3 = yangyin_cols.get("yangyin_ok3", pd.Series(False, index=df.index))

    o85 = F.LLV(open_, 21) + 0.95 * (F.HHV(open_, 21) - F.LLV(open_, 21))
    top15o = open_ >= o85
    fd15 = (close < prev_close) & (close <= open_) & (volume >= 1.2 * F.REF(volume, 1))
    cnt_bad = F.COUNT(top15o & fd15, params.cnt_bad_window)
    good_cnt_ok = cnt_bad <= 0

    avg40 = F.MA(volume, 40)
    plry = (volume > 1.95 * F.REF(volume, 1)) & (close > open_) & (volume > avg40)
    plry_cnt_ok = (F.COUNT(plry, 14) >= 2) | (F.COUNT(plry, 57) >= params.plry_long_count)
    plry_first = plry & ~_bool_ref(plry)
    plry_cont = plry & _bool_ref(plry)
    half_down = (~_bool_ref(real_yin)) & (close < prev_close) & (volume <= 0.5 * F.REF(volume, 1))
    three_sum = (
        F.COUNT(plry_first, params.three_sum_window)
        + F.COUNT(plry_cont, params.three_sum_window)
        + F.COUNT(half_down, params.three_sum_window)
    )
    three_sum_ok = three_sum >= params.three_sum_min

    maxvol = F.HHV(volume, params.maxvol_window)
    maxvol_bad = (volume == maxvol) & real_yin
    maxvol_ok = F.COUNT(maxvol_bad, params.maxvol_window) == 0

    if params.yangyin_mode == "and3":
        a1 = (
            plry_cnt_ok
            & yangyin_ok3
            & j_ok
            & good_cnt_ok
            & maxvol_ok
            & ((yangyin_ok1 & three_sum_ok) | yangyin_ok2)
        )
    else:
        a1 = (
            plry_cnt_ok
            & (yangyin_ok1 | yangyin_ok2)
            & j_ok
            & good_cnt_ok
            & three_sum_ok
            & maxvol_ok
        )

    hm_short = F.SMA(F.SMA(close, 40, 4), 100, 50)
    hm_long = _hm_long(close)
    sig_b1 = (hm_short >= hm_long * params.line_mult) & (close >= hm_long * params.line_mult) & a1

    return pd.DataFrame(
        {
            "real_yang": real_yang.fillna(False).astype(bool),
            "real_yin": real_yin.fillna(False).astype(bool),
            "j": j,
            "plry": plry.fillna(False).astype(bool),
            "plry_cnt_ok": plry_cnt_ok.fillna(False).astype(bool),
            "plry_first": plry_first.fillna(False).astype(bool),
            "plry_cont": plry_cont.fillna(False).astype(bool),
            "half_down": half_down.fillna(False).astype(bool),
            "yangyin_ok1": yangyin_ok1.fillna(False).astype(bool),
            "yangyin_ok2": yangyin_ok2.fillna(False).astype(bool),
            "yangyin_ok3": yangyin_ok3.fillna(False).astype(bool),
            "good_cnt_ok": good_cnt_ok.fillna(False).astype(bool),
            "three_sum_ok": three_sum_ok.fillna(False).astype(bool),
            "maxvol_bad": maxvol_bad.fillna(False).astype(bool),
            "maxvol_ok": maxvol_ok.fillna(False).astype(bool),
            "hm_short": hm_short,
            "hm_long": hm_long,
            "a1": a1.fillna(False).astype(bool),
            "sig_b1": sig_b1.fillna(False).astype(bool),
        },
        index=df.index,
    )
