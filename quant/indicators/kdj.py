from __future__ import annotations

import backtrader as bt


class KDJ(bt.Indicator):
    lines = ("k", "d", "j", "rsv")
    params = (
        ("n", 9),
        ("k_period", 3),
        ("d_period", 3),
    )

    def __init__(self):
        low_n = bt.indicators.Lowest(self.data.low, period=self.p.n)
        high_n = bt.indicators.Highest(self.data.high, period=self.p.n)
        denom = high_n - low_n
        self.lines.rsv = bt.If(denom == 0, 0.0, (self.data.close - low_n) / denom * 100.0)
        self.lines.k = bt.indicators.SMA(self.lines.rsv, period=self.p.k_period)
        self.lines.d = bt.indicators.SMA(self.lines.k, period=self.p.d_period)
        self.lines.j = self.lines.k * 3.0 - self.lines.d * 2.0
