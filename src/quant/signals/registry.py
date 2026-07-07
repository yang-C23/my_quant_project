"""Named signal registry."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from quant.indicators.amv import amv, amv_timing_signal

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


@register("amv_regime")
def amv_regime(df: pd.DataFrame) -> pd.Series:
    """0AMV timing regime for index daily bars."""
    return amv_timing_signal(amv(df))["regime"]
