"""
Simple moving-average crossover strategy for Backtrader.

The strategy is intentionally lightweight so it can serve as a template for
future extensions. Signals are generated on the close and executed on the next
session's open (`cheat_on_open=True` in Cerebro), mimicking the T+1 execution
rule of mainland A-shares.

Usage Example
-------------
Run via the shared backtest engine:

.. code-block:: bash

    python backtest_engine.py --symbol 000001.SZ \\
        --strategy custom_strategies.moving_average:MovingAverageCrossStrategy \\
        --strategy-params short_window=5 long_window=20

"""

from __future__ import annotations

import backtrader as bt  # type: ignore[import]

__all__ = ["MovingAverageCrossStrategy"]


class MovingAverageCrossStrategy(bt.Strategy):
    """
    5/20 moving-average crossover with T+1 execution.

    Parameters
    ----------
    short_window : int, default 5
        Lookback period for the fast moving average (e.g., 5-day MA).
    long_window : int, default 20
        Lookback period for the slow moving average (e.g., 20-day MA).
    cash_buffer : float, default 0.02
        Reserve ratio to avoid fully utilising the available cash.
    """

    params = dict(short_window=5, long_window=20, cash_buffer=0.02)

    def __init__(self) -> None:
        self.short_ma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.params.short_window
        )
        self.long_ma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.params.long_window
        )
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)
        self._pending_signal: int = 0  # 1=buy, -1=sell

    def next(self) -> None:
        if not self.position and self.crossover > 0:
            self._pending_signal = 1
        elif self.position and self.crossover < 0:
            self._pending_signal = -1

    def next_open(self) -> None:
        if self._pending_signal == 1:
            cash = self.broker.getcash() * (1 - self.params.cash_buffer)
            price = self.data.open[0]
            size = int(cash / price)
            if size > 0:
                self.buy(size=size)
        elif self._pending_signal == -1 and self.position:
            self.close()
        self._pending_signal = 0
