"""Named signal registry."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from quant.indicators.dual_trend import dual_trend
from quant.indicators.kdj import kdj

SignalFunc = Callable[[pd.DataFrame], pd.Series]

_REGISTRY: dict[str, SignalFunc] = {}


def register(name: str) -> Callable[[SignalFunc], SignalFunc]:
    """Register a named signal function."""
    if not name:
        raise ValueError("signal name must be non-empty")

    def decorator(func: SignalFunc) -> SignalFunc:
        if name in _REGISTRY:
            raise ValueError(f"signal already registered: {name}")
        _REGISTRY[name] = func
        return func

    return decorator


def get(name: str) -> SignalFunc:
    """Return a registered signal function by name."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown signal: {name}") from exc


def names() -> tuple[str, ...]:
    """Return registered signal names in stable order."""
    return tuple(sorted(_REGISTRY))


@register("kdj_oversold")
def kdj_oversold(df: pd.DataFrame) -> pd.Series:
    """J < 13 oversold trigger."""
    return (kdj(df)["j"] < 13.0).fillna(False).astype(bool)


@register("dual_trend_entry")
def dual_trend_entry(df: pd.DataFrame) -> pd.Series:
    """Dual-trend XG trigger, excluding universe-level board filters."""
    return dual_trend(df)["sig_dual_trend_entry"]
