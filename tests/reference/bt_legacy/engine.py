from __future__ import annotations

import logging

import backtrader as bt

from .strategies import DualTrendBreathStrategy, KDJForwardReturnStrategy
from quant.data.loader import build_data_feed, load_symbol_db

LOGGER = logging.getLogger("backtest_engine")


def run_kdj_forward_return_backtest(
    symbols: list[str],
    start: str | None = None,
    end: str | None = None,
    kdj_n: int = 9,
    kdj_k: int = 3,
    kdj_d: int = 3,
    j_threshold: float = 0.0,
    horizons: tuple[int, ...] = (1, 3, 5),
) -> list[dict]:
    results: list[dict] = []

    for symbol in symbols:
        try:
            df = load_symbol_db(symbol, start=start, end=end)
        except Exception as exc:
            LOGGER.warning("Skip %s: %s", symbol, exc)
            continue

        min_kdj_len = max(int(kdj_n), int(kdj_k) + int(kdj_d)) + 2
        min_len = max(max(horizons) + 2, min_kdj_len)
        if df.empty or len(df) < min_len:
            LOGGER.warning("Skip %s: not enough data (%d rows, need %d)", symbol, len(df), min_len)
            continue

        cerebro = bt.Cerebro(stdstats=False)
        datafeed = build_data_feed(symbol, df)
        cerebro.adddata(datafeed)
        cerebro.addstrategy(
            KDJForwardReturnStrategy,
            kdj_n=kdj_n,
            kdj_k=kdj_k,
            kdj_d=kdj_d,
            j_threshold=j_threshold,
            horizons=horizons,
        )

        try:
            strat = cerebro.run()[0]
            stats = strat.get_stats()
            results.append(stats)
        except Exception as exc:
            LOGGER.warning("Skip %s: backtest failed (%s)", symbol, exc)
            continue

    return results


def run_dualtrend_breath_backtest(
    symbols: list[str],
    start: str | None = None,
    end: str | None = None,
    short_period: int = 10,
    m1: int = 14,
    m2: int = 28,
    m3: int = 57,
    m4: int = 114,
    vol_window: int = 30,
    vol_ratio: float = 3.5,
    use_double_vol: bool = True,
    setup_window: int = 20,
    require_bullish_setup: bool = True,
    kdj_n: int = 9,
    kdj_k: int = 3,
    kdj_d: int = 3,
    j_low: float = 13.0,
    entry_mode: str = "j_or_zone",
    entry_require_trend: bool = True,
    entry_require_activity: bool = False,
    require_pullback: bool = True,
    filter_untradable: bool = True,
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20),
) -> list[dict]:
    results: list[dict] = []

    min_kdj_len = max(int(kdj_n), int(kdj_k) + int(kdj_d)) + 2
    min_trend_len = max(int(short_period) * 2, int(m1), int(m2), int(m3), int(m4)) + 2
    min_len = max(max(horizons) + 2, int(vol_window) + 3, min_kdj_len, min_trend_len)

    for symbol in symbols:
        try:
            df = load_symbol_db(symbol, start=start, end=end)
        except Exception as exc:
            LOGGER.warning("Skip %s: %s", symbol, exc)
            continue

        if df.empty or len(df) < min_len:
            LOGGER.warning("Skip %s: not enough data (%d rows, need %d)", symbol, len(df), min_len)
            continue

        cerebro = bt.Cerebro(stdstats=False)
        datafeed = build_data_feed(symbol, df)
        cerebro.adddata(datafeed)
        cerebro.addstrategy(
            DualTrendBreathStrategy,
            short_period=short_period,
            m1=m1,
            m2=m2,
            m3=m3,
            m4=m4,
            vol_window=vol_window,
            vol_ratio=vol_ratio,
            use_double_vol=use_double_vol,
            setup_window=setup_window,
            require_bullish_setup=require_bullish_setup,
            kdj_n=kdj_n,
            kdj_k=kdj_k,
            kdj_d=kdj_d,
            j_low=j_low,
            entry_mode=entry_mode,
            entry_require_trend=entry_require_trend,
            entry_require_activity=entry_require_activity,
            require_pullback=require_pullback,
            filter_untradable=filter_untradable,
            horizons=horizons,
        )

        try:
            strat = cerebro.run()[0]
            stats = strat.get_stats()
            results.append(stats)
        except Exception as exc:
            LOGGER.warning("Skip %s: backtest failed (%s)", symbol, exc)
            continue

    return results
