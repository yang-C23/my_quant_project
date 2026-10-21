"""Decimal cash, raw-price execution and explicit dividend receivables."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN

import pandas as pd

ZERO = Decimal("0")
CENT = Decimal("0.01")


def dec(value: object) -> Decimal:
    """Convert decimal text without importing binary float rounding into cash."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value: Decimal) -> Decimal:
    """Settle cash to cents; quantity and prices keep their own precision."""
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class Costs:
    """ETF commission assumptions; no stock stamp duty or duplicate fund TER."""

    commission_rate: Decimal = Decimal("0.0003")
    minimum_commission: Decimal = ZERO
    slippage_bps: Decimal = Decimal("5")
    dividend_tax_rate: Decimal = ZERO

    def __post_init__(self) -> None:
        if (
            min(
                self.commission_rate,
                self.minimum_commission,
                self.slippage_bps,
                self.dividend_tax_rate,
            )
            < 0
            or self.dividend_tax_rate > 1
            or self.commission_rate >= 1
            or self.slippage_bps >= 10000
        ):
            raise ValueError("invalid cost assumptions")

    def fee(self, notional: Decimal) -> Decimal:
        """No fee on a zero fill."""
        return (
            money(max(self.minimum_commission, notional * self.commission_rate))
            if notional
            else ZERO
        )


@dataclass
class Ledger:
    """One currency, arbitrary symbols; every cash mutation has a journal entry."""

    costs: Costs = field(default_factory=Costs)
    cash: Decimal = ZERO
    positions: dict[str, Decimal] = field(default_factory=dict)
    receivables: list[dict] = field(default_factory=list)
    journal: list[dict] = field(default_factory=list)
    contributions: Decimal = ZERO
    commissions: Decimal = ZERO
    slippage: Decimal = ZERO
    gross_dividends: Decimal = ZERO
    dividend_tax: Decimal = ZERO
    turnover_notional: Decimal = ZERO

    def record(self, date: object, kind: str, **fields: object) -> None:
        """Keep monetary amounts as Decimal; serializers must preserve this type."""
        self.journal.append({"date": pd.Timestamp(date), "kind": kind, **fields})

    def deposit(self, date: object, amount: Decimal) -> None:
        """External contributions do not form investment profit."""
        amount = money(dec(amount))
        if amount < 0:
            raise ValueError("use withdraw for external outflows")
        self.cash += amount
        self.contributions += amount
        self.record(date, "deposit", amount=amount)

    def withdraw(self, date: object, amount: Decimal) -> None:
        """Explicit external withdrawal, limited to settled cash."""
        amount = money(dec(amount))
        if amount < 0 or amount > self.cash:
            raise ValueError("withdrawal exceeds settled cash")
        self.cash -= amount
        self.contributions -= amount
        self.record(date, "withdrawal", amount=-amount)

    def buy(
        self,
        date: object,
        symbol: str,
        budget: Decimal,
        price: Decimal,
        lot: Decimal = Decimal("1"),
        *,
        reason: str = "scheduled",
    ) -> Decimal:
        """Buy within both budget and cash, charging explicit fees and slippage."""
        price, lot = dec(price), dec(lot)
        if price <= 0 or lot <= 0:
            raise ValueError("positive price and lot required")
        available = min(self.cash, money(dec(budget)))
        if available <= self.costs.minimum_commission:
            return ZERO
        fill = price * (1 + self.costs.slippage_bps / 10000)
        maximum_notional = min(
            available - self.costs.minimum_commission,
            available / (1 + self.costs.commission_rate),
        )
        raw_units = maximum_notional / fill
        quantity = (raw_units / lot).to_integral_value(rounding=ROUND_DOWN) * lot
        while quantity > 0:
            notional = money(quantity * fill)
            fee = self.costs.fee(notional)
            if notional + fee <= available:
                break
            quantity -= lot
        if quantity <= 0:
            return ZERO
        self.cash -= notional + fee
        self.positions[symbol] = self.positions.get(symbol, ZERO) + quantity
        self.commissions += fee
        self.slippage += money(quantity * (fill - price))
        self.turnover_notional += notional
        self.record(
            date,
            "buy",
            symbol=symbol,
            quantity=quantity,
            price=fill,
            notional=notional,
            fee=fee,
            reason=reason,
            cash=self.cash,
        )
        return quantity

    def sell(
        self,
        date: object,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        lot: Decimal = Decimal("1"),
        *,
        reason: str = "exit",
    ) -> Decimal:
        """Sell rounded lots, allowing an entire residual position to be liquidated."""
        held = self.positions.get(symbol, ZERO)
        quantity, price, lot = min(held, dec(quantity)), dec(price), dec(lot)
        if price <= 0 or lot <= 0:
            raise ValueError("positive price and lot required")
        if quantity < held:
            quantity = (quantity / lot).to_integral_value(rounding=ROUND_DOWN) * lot
        if quantity <= 0:
            return ZERO
        fill = price * (1 - self.costs.slippage_bps / 10000)
        notional = money(quantity * fill)
        fee = self.costs.fee(notional)
        if fee > notional:
            return ZERO
        self.cash += notional - fee
        self.positions[symbol] = held - quantity
        self.commissions += fee
        self.slippage += money(quantity * (price - fill))
        self.turnover_notional += notional
        self.record(
            date,
            "sell",
            symbol=symbol,
            quantity=quantity,
            price=fill,
            notional=notional,
            fee=fee,
            reason=reason,
            cash=self.cash,
        )
        return quantity

    def dividend(
        self, date: object, symbol: str, per_share: Decimal, pay_date: object, *, event_id: str
    ) -> None:
        """Create a receivable on ex-date using the entitlement before today's trades."""
        if pd.Timestamp(pay_date) < pd.Timestamp(date) or dec(per_share) < 0:
            raise ValueError("invalid dividend event")
        if any(item.get("event_id") == event_id for item in self.journal):
            raise ValueError("duplicate dividend event_id")
        gross = money(self.positions.get(symbol, ZERO) * dec(per_share))
        tax = money(gross * self.costs.dividend_tax_rate)
        self.gross_dividends += gross
        self.dividend_tax += tax
        self.receivables.append(
            {
                "id": event_id,
                "symbol": symbol,
                "pay_date": pd.Timestamp(pay_date),
                "amount": gross - tax,
            }
        )
        self.record(
            date,
            "dividend_receivable",
            symbol=symbol,
            amount=gross - tax,
            gross=gross,
            tax=tax,
            event_id=event_id,
        )

    def settle(self, date: object, *, include_today: bool) -> Decimal:
        """Pay-date after-close credit; weekend payments clear before the next session."""
        timestamp = pd.Timestamp(date)
        total, remaining = ZERO, []
        for item in self.receivables:
            due = item["pay_date"] <= timestamp if include_today else item["pay_date"] < timestamp
            if due:
                self.cash += item["amount"]
                total += item["amount"]
                self.record(
                    date,
                    "dividend_paid",
                    symbol=item["symbol"],
                    amount=item["amount"],
                    event_id=item["id"],
                )
            else:
                remaining.append(item)
        self.receivables = remaining
        return total

    def split(self, date: object, symbol: str, ratio: Decimal) -> None:
        """Adjust units; raw prices must reflect the split, dividends are separate."""
        ratio = dec(ratio)
        if ratio <= 0:
            raise ValueError("positive split ratio required")
        self.positions[symbol] = self.positions.get(symbol, ZERO) * ratio
        self.record(date, "split", symbol=symbol, ratio=ratio)

    def equity(self, prices: dict[str, Decimal]) -> Decimal:
        """Receivables contribute to equity, but not to available buying cash."""
        holdings = sum(
            (quantity * dec(prices[symbol]) for symbol, quantity in self.positions.items()), ZERO
        )
        due = sum((item["amount"] for item in self.receivables), ZERO)
        return money(self.cash + holdings + due)
