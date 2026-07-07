"""Unified qlib-backed data access API."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pandas as pd

from quant.config import get_settings
from quant.data.symbols import to_qlib

_INIT_STATE: tuple[str, str, Path] | None = None
_INIT_LOCK = threading.Lock()
_PRICE_COLUMNS = ("open", "high", "low", "close")
_DEFAULT_FIELDS = ("open", "high", "low", "close", "volume", "amount", "factor")


def _field_expr(field: str) -> str:
    return field if field.startswith("$") else f"${field}"


def _field_name(field: str) -> str:
    return field[1:] if field.startswith("$") else field


def _provider_uri(region: str, freq: str) -> Path:
    settings = get_settings()
    if freq != "day":
        raise ValueError(f"unsupported freq: {freq!r}")
    if region == "cn":
        return settings.qlib_cn_daily_uri
    if region == "us":
        return settings.qlib_us_daily_uri
    raise ValueError(f"unsupported region: {region!r}")


def init_qlib(region: str = "cn", freq: str = "day") -> None:
    """Idempotently and thread-safely initialize qlib from runtime settings.

    Concurrent ``qlib.init`` calls corrupt qlib's global config (observed as
    ``KeyError: 'dataset_cache'`` under 20-thread batch loads), so the
    double-checked lock is required, not an optimization.
    """
    global _INIT_STATE

    provider_uri = _provider_uri(region, freq)
    state = (region, freq, provider_uri)
    if _INIT_STATE == state:
        return

    with _INIT_LOCK:
        if _INIT_STATE == state:
            return

        import qlib

        qlib.init(
            provider_uri=str(provider_uri),
            region=region,
            expression_cache=None,
            dataset_cache=None,
        )
        _INIT_STATE = state


def _flatten_single_symbol(features: pd.DataFrame, qlib_symbol: str) -> pd.DataFrame:
    frame = features.copy()
    if isinstance(frame.index, pd.MultiIndex):
        level = "instrument" if "instrument" in frame.index.names else 0
        try:
            frame = frame.xs(qlib_symbol, level=level)
        except KeyError:
            return pd.DataFrame(columns=frame.columns)
    frame.index = pd.to_datetime(frame.index)
    frame = frame.sort_index()
    frame.columns = [_field_name(str(col)) for col in frame.columns]
    return frame


def get_features(
    symbols: Sequence[str],
    fields: Sequence[str],
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load raw qlib feature expressions for one or more internal symbols."""
    if not symbols:
        raise ValueError("symbols must be non-empty")
    if not fields:
        raise ValueError("fields must be non-empty")

    init_qlib()
    from qlib.data import D

    instruments = [to_qlib(symbol) for symbol in symbols]
    expressions = [_field_expr(field) for field in fields]
    return D.features(
        instruments,
        expressions,
        start_time=start,
        end_time=end,
        disk_cache=0,
    )


def _latest_factor(qlib_symbol: str) -> float:
    from qlib.data import D

    factor = D.features([qlib_symbol], ["$factor"], disk_cache=0)
    frame = _flatten_single_symbol(factor, qlib_symbol)
    values = frame["factor"].dropna()
    if values.empty:
        raise ValueError(f"missing factor for {qlib_symbol}")
    return float(values.iloc[-1])


def get_ohlcv(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    *,
    adjust: Literal["qfq", "hfq", "raw"] = "qfq",
    freq: str = "day",
    fields: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Load OHLCV for one symbol.

    qlib stores hfq-adjusted prices and volumes. ``raw`` reverses that
    adjustment. ``qfq`` divides prices by the latest available factor, so
    qfq values drift when the underlying data is updated; reproducible
    research should use ``hfq`` or record the data snapshot date.
    """
    if adjust not in {"qfq", "hfq", "raw"}:
        raise ValueError(f"unsupported adjust: {adjust!r}")
    if freq != "day":
        raise ValueError(f"unsupported freq: {freq!r}")

    qlib_symbol = to_qlib(symbol)
    requested = tuple(fields or _DEFAULT_FIELDS)
    fetch_fields = list(dict.fromkeys([*requested, "factor"]))
    features = get_features([symbol], fetch_fields, start, end)
    frame = _flatten_single_symbol(features, qlib_symbol)
    if frame.empty:
        raise ValueError(f"no OHLCV data for {symbol}")

    out = frame.copy()
    price_cols = [col for col in _PRICE_COLUMNS if col in out.columns]
    numeric_cols = [*price_cols, "factor"]
    if "volume" in out.columns:
        numeric_cols.append("volume")
    for col in numeric_cols:
        out[col] = out[col].astype(float)
    factor = out["factor"]
    if adjust == "raw":
        out.loc[:, price_cols] = out.loc[:, price_cols].astype(float).div(factor, axis=0)
        if "volume" in out.columns:
            out["volume"] = out["volume"].astype(float) * factor
    elif adjust == "qfq":
        latest = _latest_factor(qlib_symbol)
        out.loc[:, price_cols] = out.loc[:, price_cols].astype(float) / latest
        if "volume" in out.columns:
            out["volume"] = out["volume"].astype(float) * latest

    out = out[[_field_name(field) for field in requested]]
    out.index.name = "date"
    return out
