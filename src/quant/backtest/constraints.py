"""A-share tradability checks and a per-symbol T+1 availability ledger."""

from __future__ import annotations

import math

import backtrader as bt
import pandas as pd


class AShareConstraints:
    """Stateless bar checks plus a ledger of buys that become sellable next day."""

    def __init__(self) -> None:
        self._bought_by_date: dict[pd.Timestamp, int] = {}

    @staticmethod
    def round_lots(size: int) -> int:
        """Round a requested share count down to the nearest 100-share lot."""
        return max(int(size), 0) // 100 * 100

    @staticmethod
    def _line_value(data: object, name: str) -> float | None:
        try:
            value = float(getattr(data, name)[0])
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    @staticmethod
    def _data_date(data: object) -> pd.Timestamp:
        datetime_line = getattr(data, "datetime")
        if hasattr(datetime_line, "date"):
            return pd.Timestamp(datetime_line.date(0)).normalize()
        return pd.Timestamp(bt.num2date(datetime_line[0])).normalize()

    @classmethod
    def _is_tradable_bar(cls, data: object) -> bool:
        suspended = cls._line_value(data, "is_suspended")
        # -1 is the feed's missing-data sentinel. Unknown must not become an
        # apparently tradable bar merely because Backtrader stores floats.
        return suspended == 0.0

    def can_buy(self, data: object) -> bool:
        """Allow buys only off suspension and away from an open-at-limit-up bar."""
        if not self._is_tradable_bar(data):
            return False
        raw_open = self._line_value(data, "raw_open")
        if raw_open is None:
            return False
        limit_up = self._line_value(data, "limit_up_price")
        return limit_up is None or raw_open < limit_up

    def can_sell(self, data: object, size: int) -> bool:
        """Allow sells only when the bar is tradable, unlocked, and T+1 eligible."""
        if size <= 0 or not self._is_tradable_bar(data):
            return False
        raw_open = self._line_value(data, "raw_open")
        if raw_open is None:
            return False
        limit_down = self._line_value(data, "limit_down_price")
        if limit_down is not None and raw_open <= limit_down:
            return False
        return self.sellable(self._data_date(data)) >= size

    def on_buy_filled(self, dt: object, size: int) -> None:
        """Record a filled buy; shares unlock for selling on the next date."""
        if size <= 0:
            raise ValueError("size must be positive")
        date = pd.Timestamp(dt).normalize()
        self._bought_by_date[date] = self._bought_by_date.get(date, 0) + int(size)

    def sellable(self, dt: object) -> int:
        """Return cumulative shares acquired strictly before ``dt``."""
        date = pd.Timestamp(dt).normalize()
        return sum(size for bought_date, size in self._bought_by_date.items() if bought_date < date)
