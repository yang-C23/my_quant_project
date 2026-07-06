"""Legacy Backtrader TDXSMA reference kept for TASK-020 golden generation."""

from __future__ import annotations

import math

import backtrader as bt


class TDXSMA(bt.Indicator):
    """Backtrader implementation of the TDX SMA recurrence."""

    lines = ("sma",)
    params = (
        ("period", 1),
        ("m", 1),
    )

    def __init__(self) -> None:
        self.addminperiod(1)

    def next(self) -> None:
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
