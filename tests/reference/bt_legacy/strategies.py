from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import backtrader as bt
import numpy as np

from .dual_trend import DualTrend
from .kdj import KDJ
from .kdj_tdx import KDJTDX
from .volume_breath import VolumeBreath


@dataclass
class HorizonStats:
    count: int
    win_rate: float
    avg_return: float
    median_return: float
    p25_return: float
    p75_return: float


class KDJForwardReturnStrategy(bt.Strategy):
    params = (
        ("kdj_n", 9),
        ("kdj_k", 3),
        ("kdj_d", 3),
        ("j_threshold", 0.0),
        ("horizons", (1, 3, 5)),
    )

    def __init__(self):
        self.kdj = KDJ(
            self.data,
            n=self.p.kdj_n,
            k_period=self.p.kdj_k,
            d_period=self.p.kdj_d,
        )
        self.horizons = sorted(set(int(h) for h in self.p.horizons))
        self.max_horizon = max(self.horizons) if self.horizons else 0
        self.pending: list[dict] = []
        self.returns: dict[int, list[float]] = {h: [] for h in self.horizons}
        self.signal_count = 0

    def next(self):
        if len(self.data) < 2:
            return

        current_index = len(self.data) - 1
        prev_j = float(self.kdj.j[-1])

        if prev_j < self.p.j_threshold:
            entry_price = float(self.data.open[0])
            entry_date = self.data.datetime.date(0)
            self.pending.append(
                {
                    "index": current_index,
                    "price": entry_price,
                    "date": entry_date,
                    "done": set(),
                }
            )
            self.signal_count += 1

        if not self.pending or self.max_horizon <= 0:
            return

        remaining = []
        for item in self.pending:
            delta = current_index - item["index"]
            if delta <= 0:
                remaining.append(item)
                continue

            if delta in self.horizons and delta not in item["done"]:
                ret = float(self.data.close[0]) / item["price"] - 1.0
                self.returns[delta].append(ret)
                item["done"].add(delta)

            if delta < self.max_horizon:
                remaining.append(item)
            elif len(item["done"]) < len(self.horizons):
                remaining.append(item)

        self.pending = remaining

    def _calc_stats(self, values: Iterable[float]) -> HorizonStats:
        vals = np.asarray(list(values), dtype=float)
        if len(vals) == 0:
            return HorizonStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)

        win_rate = float((vals > 0).mean())
        avg_return = float(vals.mean())
        median_return = float(np.median(vals))
        p25_return = float(np.percentile(vals, 25))
        p75_return = float(np.percentile(vals, 75))
        return HorizonStats(
            count=len(vals),
            win_rate=win_rate,
            avg_return=avg_return,
            median_return=median_return,
            p25_return=p25_return,
            p75_return=p75_return,
        )

    def get_stats(self) -> dict:
        horizon_stats = {h: self._calc_stats(self.returns[h]) for h in self.horizons}
        return {
            "symbol": self.data._name or "UNKNOWN",
            "signal_count": int(self.signal_count),
            "horizon_stats": horizon_stats,
            "returns": self.returns,
        }


class DualTrendBreathStrategy(bt.Strategy):
    params = (
        ("short_period", 10),
        ("m1", 14),
        ("m2", 28),
        ("m3", 57),
        ("m4", 114),
        ("vol_window", 30),
        ("vol_ratio", 3.5),
        ("use_double_vol", True),
        ("setup_window", 20),
        ("require_bullish_setup", True),
        ("kdj_n", 9),
        ("kdj_k", 3),
        ("kdj_d", 3),
        ("j_low", 13.0),
        ("entry_mode", "j_or_zone"),
        ("require_trend", True),
        ("require_activity", True),
        ("entry_require_trend", True),
        ("entry_require_activity", False),
        ("require_pullback", True),
        ("filter_untradable", True),
        ("horizons", (1, 3, 5, 10, 20)),
    )

    def __init__(self):
        self.trend = DualTrend(
            self.data,
            short_period=self.p.short_period,
            m1=self.p.m1,
            m2=self.p.m2,
            m3=self.p.m3,
            m4=self.p.m4,
        )
        self.kdj = KDJTDX(
            self.data,
            n=self.p.kdj_n,
            k_period=self.p.kdj_k,
            d_period=self.p.kdj_d,
        )
        self.vol_breath = VolumeBreath(
            self.data,
            window=self.p.vol_window,
            ratio=self.p.vol_ratio,
        )
        self.horizons = sorted(set(int(h) for h in self.p.horizons))
        self.max_horizon = max(self.horizons) if self.horizons else 0
        self.pending: list[dict] = []
        self.returns: dict[int, list[float]] = {h: [] for h in self.horizons}
        self.signal_count = 0
        self.setup_countdown = 0
        self._has_flags = all(
            hasattr(self.data, attr)
            for attr in ("is_suspended", "is_upper_limit", "is_lower_limit")
        )

    def _entry_blocked_today(self) -> bool:
        if not self.p.filter_untradable:
            return False
        if not self._has_flags:
            return False
        return bool(self.data.is_suspended[0]) or bool(self.data.is_upper_limit[0])

    def _signal_blocked_prev(self) -> bool:
        if not self.p.filter_untradable:
            return False
        if not self._has_flags:
            return False
        return bool(self.data.is_suspended[-1]) or bool(self.data.is_upper_limit[-1])

    def _double_volume_prev(self) -> bool:
        window = max(int(self.p.vol_window), 2)
        if len(self.data) < window + 1 or len(self.data) < 3:
            return False

        size = window + 1
        vols = list(self.data.volume.get(size=size))
        if len(vols) < 3:
            return False

        prev_vol = float(vols[-2])
        prev_prev_vol = float(vols[-3])
        if prev_prev_vol <= 0:
            return False

        window_vols = [float(v) for v in vols[:-1]]
        max_vol = max(window_vols) if window_vols else prev_vol
        return prev_vol >= 2.0 * prev_prev_vol and prev_vol >= max_vol

    def _setup_signal_prev(self) -> bool:
        short_prev = float(self.trend.short_trend[-1])
        long_prev = float(self.trend.long_trend[-1])
        close_prev = float(self.data.close[-1])
        open_prev = float(self.data.open[-1])

        trend_ok = short_prev > long_prev if self.p.entry_require_trend else True
        activity_ok = bool(self.vol_breath.activity[-1]) if self.p.entry_require_activity else True
        bullish_ok = close_prev > open_prev if self.p.require_bullish_setup else True

        return (
            trend_ok
            and activity_ok
            and bullish_ok
            and self._double_volume_prev()
            and not self._signal_blocked_prev()
        )

    def _entry_condition_prev(self) -> bool:
        short_prev = float(self.trend.short_trend[-1])
        long_prev = float(self.trend.long_trend[-1])
        close_prev = float(self.data.close[-1])

        trend_ok = short_prev > long_prev if self.p.require_trend else True
        activity_ok = bool(self.vol_breath.activity[-1]) if self.p.require_activity else True
        entry_j = float(self.kdj.j[-1]) < self.p.j_low
        price_zone = close_prev < short_prev and close_prev > long_prev

        mode = str(self.p.entry_mode or "").lower()
        if mode == "j_only":
            entry_ok = entry_j
        elif mode == "zone_only":
            entry_ok = price_zone
        elif mode == "j_and_zone":
            entry_ok = entry_j and price_zone
        else:
            entry_ok = entry_j or price_zone

        pullback_ok = True
        if self.p.require_pullback:
            if len(self.data) < 3:
                return False
            close_prevprev = float(self.data.close[-2])
            vol_prev = float(self.data.volume[-1])
            vol_prevprev = float(self.data.volume[-2])
            pullback_ok = close_prev < close_prevprev and vol_prev < vol_prevprev

        return (
            trend_ok
            and activity_ok
            and entry_ok
            and pullback_ok
            and not self._signal_blocked_prev()
        )

    def next(self):
        if len(self.data) < 2:
            return

        current_index = len(self.data) - 1
        if self.p.use_double_vol and self._setup_signal_prev():
            self.setup_countdown = int(self.p.setup_window)

        entry_window_ok = (not self.p.use_double_vol) or self.setup_countdown > 0
        if entry_window_ok and self._entry_condition_prev() and not self._entry_blocked_today():
            entry_price = float(self.data.open[0])
            entry_date = self.data.datetime.date(0)
            self.pending.append(
                {
                    "index": current_index,
                    "price": entry_price,
                    "date": entry_date,
                    "done": set(),
                }
            )
            self.signal_count += 1

        if self.setup_countdown > 0:
            self.setup_countdown -= 1

        if not self.pending or self.max_horizon <= 0:
            return

        remaining = []
        for item in self.pending:
            delta = current_index - item["index"]
            if delta <= 0:
                remaining.append(item)
                continue

            if delta in self.horizons and delta not in item["done"]:
                ret = float(self.data.close[0]) / item["price"] - 1.0
                self.returns[delta].append(ret)
                item["done"].add(delta)

            if delta < self.max_horizon:
                remaining.append(item)
            elif len(item["done"]) < len(self.horizons):
                remaining.append(item)

        self.pending = remaining

    def _calc_stats(self, values: Iterable[float]) -> HorizonStats:
        vals = np.asarray(list(values), dtype=float)
        if len(vals) == 0:
            return HorizonStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)

        win_rate = float((vals > 0).mean())
        avg_return = float(vals.mean())
        median_return = float(np.median(vals))
        p25_return = float(np.percentile(vals, 25))
        p75_return = float(np.percentile(vals, 75))
        return HorizonStats(
            count=len(vals),
            win_rate=win_rate,
            avg_return=avg_return,
            median_return=median_return,
            p25_return=p25_return,
            p75_return=p75_return,
        )

    def get_stats(self) -> dict:
        horizon_stats = {h: self._calc_stats(self.returns[h]) for h in self.horizons}
        return {
            "symbol": self.data._name or "UNKNOWN",
            "signal_count": int(self.signal_count),
            "horizon_stats": horizon_stats,
            "returns": self.returns,
        }
