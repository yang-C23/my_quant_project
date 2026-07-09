"""Signal-level factor wrappers and universe filters."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd

from quant.data.api import get_ohlcv_batch
from quant.data.symbols import to_qlib
from quant.indicators.b1 import B1Params, b1
from quant.indicators.kdj import kdj
from quant.indicators.volume_patterns import volume_patterns

FactorFunc = Callable[[pd.DataFrame, dict | None], pd.Series]

_FACTOR_REGISTRY: dict[str, FactorFunc] = {}


def register_factor(name: str) -> Callable[[FactorFunc], FactorFunc]:
    """Register a continuous factor function."""
    if not name:
        raise ValueError("factor name must be non-empty")

    def decorator(func: FactorFunc) -> FactorFunc:
        if name in _FACTOR_REGISTRY:
            raise ValueError(f"factor already registered: {name}")
        _FACTOR_REGISTRY[name] = func
        return func

    return decorator


def factor_names() -> tuple[str, ...]:
    """Return registered continuous factor names."""
    return tuple(sorted(_FACTOR_REGISTRY))


def b1_signal_with_universe(
    df: pd.DataFrame, params: B1Params, *, min_float_mktcap: float = 50e8
) -> pd.Series:
    """Return B1 signal with optional universe-side market-cap filtering.

    The indicator itself does not implement MVOK or board exclusions. When
    ``float_mktcap`` is present, this wrapper applies ``float_mktcap >=
    min_float_mktcap``. Board filters belong to the caller's universe layer.
    """
    signal = b1(df, params)["sig_b1"]
    if "float_mktcap" not in df.columns:
        return signal
    return signal & df["float_mktcap"].astype(float).ge(min_float_mktcap).fillna(False)


def _compute_one_signal(
    name: str,
    symbol: str,
    data: pd.DataFrame,
    signal_params: dict | None,
) -> pd.DataFrame:
    if name == "kdj_oversold" and signal_params and "j_threshold" in signal_params:
        frame = kdj(data, sma_mode=signal_params.get("sma_mode", "tdx"))
        signal = (frame["j"] < float(signal_params["j_threshold"])).fillna(False)
    else:
        from quant.signals import registry

        signal = registry.get(name)(data)
    return pd.DataFrame({"symbol": symbol, "date": data.index, "sig": signal.to_numpy(bool)})


def compute_signal(
    name: str,
    symbols: Sequence[str],
    start: str | None = None,
    end: str | None = None,
    *,
    signal_params: dict | None = None,
    workers: int | None = None,
) -> pd.DataFrame:
    """Compute a registered signal for many symbols."""
    del workers
    if not symbols:
        return pd.DataFrame(columns=["symbol", "date", "sig"])

    frames: list[pd.DataFrame] = []
    prices = get_ohlcv_batch(symbols, start=start, end=end, adjust="qfq")
    for symbol, group in prices.groupby("symbol", sort=True):
        data = group.drop(columns=["symbol"]).set_index("date")
        frame = _compute_one_signal(name, symbol, data, signal_params)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "sig"])
    return (
        pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)
    )


_FACTOR_FIELDS = ("open", "high", "low", "close", "volume", "amount", "factor", "turnover")


def _compute_one_factor(
    name: str,
    symbol: str,
    data: pd.DataFrame,
    params: dict | None,
) -> pd.DataFrame:
    factor = _FACTOR_REGISTRY[name](data, params).astype(float)
    return pd.DataFrame({"symbol": symbol, "date": data.index, "factor": factor.to_numpy()})


def compute_factor_frame(
    name: str,
    symbols: Sequence[str],
    start: str | None = None,
    end: str | None = None,
    *,
    params: dict | None = None,
    workers: int | None = None,
) -> pd.DataFrame:
    """Compute a registered continuous factor for many symbols."""
    del workers
    if name not in _FACTOR_REGISTRY:
        raise KeyError(f"unknown factor: {name}")
    if not symbols:
        return pd.DataFrame(columns=["symbol", "date", "factor"])
    prices = get_ohlcv_batch(symbols, start=start, end=end, adjust="qfq", fields=_FACTOR_FIELDS)
    frames: list[pd.DataFrame] = []
    for symbol, group in prices.groupby("symbol", sort=True):
        data = group.drop(columns=["symbol"]).set_index("date")
        frame = _compute_one_factor(name, symbol, data, params).dropna(subset=["factor"])
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "factor"])
    return (
        pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)
    )


def to_factor(
    name: str, symbols: Sequence[str], start: str | None = None, end: str | None = None
) -> pd.Series:
    """Return a qlib-compatible factor Series indexed by (datetime, instrument)."""
    signals = compute_signal(name, symbols, start, end)
    if signals.empty:
        return pd.Series(dtype=float, name=name)
    frame = signals.copy()
    frame["datetime"] = pd.to_datetime(frame["date"])
    frame["instrument"] = frame["symbol"].map(to_qlib)
    frame[name] = frame["sig"].astype(float)
    return frame.set_index(["datetime", "instrument"])[name].sort_index()


@register_factor("mom_20")
def factor_mom_20(df: pd.DataFrame, params: dict | None = None) -> pd.Series:
    """Close-to-close momentum over the trailing 20 trading days."""
    window = int((params or {}).get("window", 20))
    return df["close"].astype(float).pct_change(window, fill_method=None)


@register_factor("washout_area_ratio")
def factor_washout_area_ratio(df: pd.DataFrame, params: dict | None = None) -> pd.Series:
    """Green/red volume area ratio over a rolling window."""
    window = int((params or {}).get("window", 60))
    return volume_patterns(df, dead_window=window)["washout_area_ratio"]


@register_factor("red_green_vol_ratio")
def factor_red_green_vol_ratio(df: pd.DataFrame, params: dict | None = None) -> pd.Series:
    """Rolling positive-candle volume divided by negative-candle volume."""
    window = int((params or {}).get("window", 28))
    volume = df["volume"].astype(float)
    red = (
        volume.where(df["close"].astype(float) >= df["open"].astype(float), 0.0)
        .rolling(window)
        .sum()
    )
    green = (
        volume.where(df["close"].astype(float) < df["open"].astype(float), 0.0)
        .rolling(window)
        .sum()
    )
    return (red / green).where(green != 0)


@register_factor("bottom_area_score")
def factor_bottom_area_score(df: pd.DataFrame, params: dict | None = None) -> pd.Series:
    """Washout area ratio gated to the lower price area."""
    params = params or {}
    window = int(params.get("window", 60))
    price_window = int(params.get("price_window", 120))
    close = df["close"].astype(float)
    q30 = close.rolling(price_window).quantile(0.3)
    return factor_washout_area_ratio(df, {"window": window}).where(close <= q30)


@register_factor("turnover_weighted_cost")
def factor_turnover_weighted_cost(df: pd.DataFrame, params: dict | None = None) -> pd.Series:
    """Close relative to rolling turnover-weighted cost."""
    window = int((params or {}).get("window", 60))
    if "turnover" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    turnover = df["turnover"].astype(float).where(df["turnover"].astype(float) > 0)
    close = df["close"].astype(float)
    cost = (close * turnover).rolling(window).sum() / turnover.rolling(window).sum()
    return close / cost - 1.0


@register_factor("chip_concentration")
def factor_chip_concentration(df: pd.DataFrame, params: dict | None = None) -> pd.Series:
    """Rolling amount-weighted price dispersion divided by weighted mean."""
    window = int((params or {}).get("window", 60))
    weight = df["amount"].astype(float).where(df["amount"].astype(float) > 0)
    price = df["close"].astype(float)
    mean = (price * weight).rolling(window).sum() / weight.rolling(window).sum()
    second = ((price**2) * weight).rolling(window).sum() / weight.rolling(window).sum()
    variance = (second - mean**2).clip(lower=0)
    return np.sqrt(variance) / mean
