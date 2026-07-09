"""A-share transaction costs shared by Backtrader verification runs."""

from __future__ import annotations

from dataclasses import dataclass
import math

import backtrader as bt
import pandas as pd

_STAMP_TAX_CUTOVER = pd.Timestamp("2023-08-28")
_DEFAULT_COMMISSION_DATE = _STAMP_TAX_CUTOVER


@dataclass(frozen=True)
class AShareCosts:
    """A-share fee schedule from ``docs/backtest_platform.md`` section 3."""

    commission_rate: float = 2.5e-4
    commission_min: float = 5.0
    stamp_tax_rate: float = 5e-4
    transfer_fee_rate: float = 1e-5
    slippage_rate: float = 1e-3

    def stamp_rate_at(self, date: pd.Timestamp) -> float:
        """Return the sell-side stamp-tax rate effective on ``date``."""
        effective_date = pd.Timestamp(date).normalize()
        if effective_date < _STAMP_TAX_CUTOVER:
            return 1e-3
        return self.stamp_tax_rate

    def side_cost(self, *, price: float, size: int, is_sell: bool, date: pd.Timestamp) -> float:
        """Return one side's commission, transfer fee, and applicable stamp tax."""
        if not math.isfinite(price) or price < 0:
            raise ValueError("price must be finite and non-negative")
        if size < 0:
            raise ValueError("size must be non-negative")
        if price == 0 or size == 0:
            return 0.0

        notional = price * size
        commission = max(notional * self.commission_rate, self.commission_min)
        transfer_fee = notional * self.transfer_fee_rate
        stamp_tax = notional * self.stamp_rate_at(date) if is_sell else 0.0
        return commission + transfer_fee + stamp_tax


class AShareCommission(bt.CommInfoBase):
    """Bridge :class:`AShareCosts` into Backtrader's commission callback.

    Backtrader only provides ``size`` and ``price`` to ``_getcommission``.
    Its execution date must therefore be supplied by the caller through
    :meth:`set_trade_date` before an order is submitted. The default is the
    2023-08-28 post-reform rate, matching ``AShareCosts.stamp_tax_rate``.
    """

    params: tuple[()] = ()

    def __init__(self, costs: AShareCosts) -> None:
        super().__init__()
        self.costs = costs
        self._trade_date = _DEFAULT_COMMISSION_DATE

    def set_trade_date(self, date: pd.Timestamp) -> None:
        """Set the settlement date used by the next commission calculation."""
        self._trade_date = pd.Timestamp(date).normalize()

    def _getcommission(self, size: float, price: float, pseudoexec: bool) -> float:
        del pseudoexec
        return self.costs.side_cost(
            price=float(price),
            size=abs(int(size)),
            is_sell=size < 0,
            date=self._trade_date,
        )
