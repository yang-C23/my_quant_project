from __future__ import annotations

import backtrader as bt


class DualTrend(bt.Indicator):
    lines = ("short_trend", "long_trend")
    params = (
        ("short_period", 10),
        ("m1", 14),
        ("m2", 28),
        ("m3", 57),
        ("m4", 114),
    )

    def __init__(self):
        short_ema = bt.indicators.EMA(self.data.close, period=self.p.short_period)
        self.lines.short_trend = bt.indicators.EMA(short_ema, period=self.p.short_period)

        ma1 = bt.indicators.SMA(self.data.close, period=self.p.m1)
        ma2 = bt.indicators.SMA(self.data.close, period=self.p.m2)
        ma3 = bt.indicators.SMA(self.data.close, period=self.p.m3)
        ma4 = bt.indicators.SMA(self.data.close, period=self.p.m4)
        self.lines.long_trend = (ma1 + ma2 + ma3 + ma4) / 4.0
