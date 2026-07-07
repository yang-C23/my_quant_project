"""Named signal registry."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from quant.indicators.amv import amv, amv_timing_signal
from quant.indicators.b1 import PRESETS as B1_PRESETS
from quant.indicators.brick_osc import PRESETS as BRICK_PRESETS
from quant.indicators.brick_osc import brick_osc
from quant.indicators.dual_trend import dual_trend
from quant.indicators.kdj import kdj
from quant.indicators.volume_patterns import single_needle_proxy, volume_patterns
from quant.indicators.zhixing_macd import zhixing_macd
from quant.signals.factors import b1_signal_with_universe

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


@register("kdj_oversold")
def kdj_oversold(df: pd.DataFrame) -> pd.Series:
    """J < 13 oversold trigger."""
    return (kdj(df)["j"] < 13.0).fillna(False).astype(bool)


@register("dual_trend_entry")
def dual_trend_entry(df: pd.DataFrame) -> pd.Series:
    """Dual-trend XG trigger, excluding universe-level board filters."""
    return dual_trend(df)["sig_dual_trend_entry"]


@register("b1_v242_62")
def b1_v242_62(df: pd.DataFrame) -> pd.Series:
    """B1 v2.42.62 signal; MVOK is applied here when float_mktcap exists."""
    return b1_signal_with_universe(df, B1_PRESETS["b1_v242_62"])


@register("b1_v242b")
def b1_v242b(df: pd.DataFrame) -> pd.Series:
    """B1 v2.42b signal; MVOK is applied here when float_mktcap exists."""
    return b1_signal_with_universe(df, B1_PRESETS["b1_v242b"])


@register("b1_v242p")
def b1_v242p(df: pd.DataFrame) -> pd.Series:
    """B1 v2.42p signal; MVOK is applied here when float_mktcap exists."""
    return b1_signal_with_universe(df, B1_PRESETS["b1_v242p"])


@register("double_vol_yang")
def double_vol_yang(df: pd.DataFrame) -> pd.Series:
    """Double-volume positive candle."""
    return volume_patterns(df)["sig_double_vol_yang"]


@register("triple_dvy")
def triple_dvy(df: pd.DataFrame) -> pd.Series:
    """Three consecutive double-volume positive candles with rising price."""
    return volume_patterns(df)["sig_triple_dvy"]


@register("single_needle_proxy")
def single_needle_proxy_signal(df: pd.DataFrame) -> pd.Series:
    """Shape-only proxy for the proprietary single-needle signal."""
    return single_needle_proxy(df)["sig_single_needle"]


@register("zhixing_macd_cross")
def zhixing_macd_cross(df: pd.DataFrame) -> pd.Series:
    """DIFF zero-axis cross marker from ZhiXing MACD."""
    macd = zhixing_macd(df)
    return macd["sig_diff_cross_up_zero"] | macd["sig_diff_cross_dn_zero"]


@register("brick_strict")
def brick_strict(df: pd.DataFrame) -> pd.Series:
    """Strict brick oscillator stock-picking variant."""
    return brick_osc(df, BRICK_PRESETS["strict"])["sig_brick_strict"]


@register("brick_relaxed")
def brick_relaxed(df: pd.DataFrame) -> pd.Series:
    """Relaxed brick oscillator stock-picking variant."""
    return brick_osc(df, BRICK_PRESETS["relaxed"])["sig_brick_relaxed"]


@register("brick_len")
def brick_len(df: pd.DataFrame) -> pd.Series:
    """Length-checked brick oscillator stock-picking variant."""
    return brick_osc(df, BRICK_PRESETS["len_checked"])["sig_brick_len"]
