from __future__ import annotations

import logging
from pathlib import Path

import backtrader as bt

from quant.backtest.strategies import KDJForwardReturnStrategy
from quant.data.loader import build_data_feed, load_symbol_csv

LOGGER = logging.getLogger("backtest_engine")


def run_kdj_forward_return_backtest(
    symbols: list[str],
    data_dir: str | Path,
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
            df = load_symbol_csv(symbol, data_dir=data_dir, start=start, end=end)
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
