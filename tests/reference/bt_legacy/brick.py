from __future__ import annotations

import math

import backtrader as bt


class TDXSMA(bt.Indicator):
    lines = ("sma",)
    params = (
        ("period", 1),
        ("m", 1),
    )

    def __init__(self):
        self.addminperiod(1)

    def next(self):
        val = float(self.data[0])
        if math.isnan(val):
            prev_val = float(self.lines.sma[-1]) if len(self.data) > 1 else 0.0
            val = 0.0 if math.isnan(prev_val) else prev_val

        if len(self.data) == 1:
            self.lines.sma[0] = val
            return

        prev = float(self.lines.sma[-1])
        if math.isnan(prev):
            prev = val

        self.lines.sma[0] = (self.p.m * val + (self.p.period - self.p.m) * prev) / float(
            self.p.period
        )


class BrickIndicator(bt.Indicator):
    lines = ("brick", "aa", "bb", "xg")
    params = (
        ("window", 4),
        ("sma1", 4),
        ("sma2", 6),
        ("sma3", 6),
        ("threshold", 4.0),
        ("sma_m", 1),
    )

    def __init__(self):
        min_period = max(self.p.window, self.p.sma1, self.p.sma2, self.p.sma3)
        self.addminperiod(min_period)

        high_n = bt.indicators.Highest(self.data.high, period=self.p.window)
        low_n = bt.indicators.Lowest(self.data.low, period=self.p.window)
        denom = high_n - low_n

        var1a = bt.If(denom == 0, 0.0, (high_n - self.data.close) / denom * 100.0 - 90.0)
        var2a = TDXSMA(var1a, period=self.p.sma1, m=self.p.sma_m) + 100.0

        var3a = bt.If(denom == 0, 0.0, (self.data.close - low_n) / denom * 100.0)
        var4a = TDXSMA(var3a, period=self.p.sma2, m=self.p.sma_m)
        var5a = TDXSMA(var4a, period=self.p.sma3, m=self.p.sma_m) + 100.0

        var6a = var5a - var2a
        self.lines.brick = bt.If(var6a > self.p.threshold, var6a - self.p.threshold, 0.0)

        self.lines.aa = self.lines.brick > self.lines.brick(-1)
        self.lines.bb = self.lines.brick < self.lines.brick(-1)
        self.lines.xg = bt.And(self.lines.aa, self.lines.aa(-1) == 0)
