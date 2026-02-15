from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import backtrader as bt
import numpy as np

from quant.indicators.kdj import KDJ


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
            entry_price = float(self.data.close[-1])
            entry_date = self.data.datetime.date(-1)
            self.pending.append(
                {
                    "index": current_index - 1,
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
