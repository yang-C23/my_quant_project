"""Same-market style portfolios with annual rebalancing and identical funding."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from quant.longterm.engine import Backtest, performance
from quant.longterm.ledger import Costs, Ledger, ZERO, dec


def run_allocation(
    bars: dict[str, pd.DataFrame],
    *,
    initial: float = 100000,
    monthly: float = 1000,
    weights: dict[str, float] | None = None,
    tranches: int = 12,
    costs: Costs | None = None,
    actions: dict[str, pd.DataFrame] | None = None,
    lot: Decimal = Decimal("1"),
    reinvest_dividends: bool = True,
) -> Backtest:
    """Rebalance at the first common session of each year, without future prices.

    Caller must provide same-market raw prices with verified split/dividend
    actions for an investable result. Missing-action runs are price-only probes.
    """
    if len(bars) < 2 or tranches < 1 or initial <= 0 or monthly < 0:
        raise ValueError("invalid portfolio funding or universe")
    weights = weights or {symbol: 1 / len(bars) for symbol in bars}
    if (
        set(weights) != set(bars)
        or not np.isclose(sum(weights.values()), 1)
        or min(weights.values()) < 0
    ):
        raise ValueError("weights must be nonnegative and sum to one")
    calendar = None
    for frame in bars.values():
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError("invalid asset calendar")
        if not {"open", "close"}.issubset(frame):
            raise ValueError("open and close required")
        calendar = frame.index if calendar is None else calendar.intersection(frame.index)
    if calendar is None or len(calendar) < 2:
        raise ValueError("insufficient common calendar")
    ledger = Ledger(costs=costs or Costs())
    event_map: dict[pd.Timestamp, list[dict]] = {}
    for symbol, events in (actions or {}).items():
        for event in events.to_dict("records"):
            date = pd.Timestamp(event["ex_date"])
            if date not in calendar:
                raise ValueError("action date not in common calendar")
            event_map.setdefault(date, []).append({**event, "symbol": symbol})
    budget = dec(initial)
    tranche = budget / tranches
    last_month, last_year = None, None
    protected = ZERO
    rows = []
    for i, date in enumerate(calendar):
        month = (date.year, date.month)
        monthly_day = month != last_month
        flow = dec(initial) if i == 0 else dec(monthly) if monthly_day else ZERO
        if flow:
            ledger.deposit(date, flow)
        paid = ledger.settle(date, include_today=False)
        if not reinvest_dividends:
            protected += paid
        for event in event_map.get(date, []):
            if event["kind"] == "split":
                ledger.split(date, event["symbol"], dec(event["ratio"]))
            elif event["kind"] == "dividend":
                if pd.isna(event.get("pay_date")):
                    raise ValueError("actual dividend pay dates required")
                ledger.dividend(
                    date,
                    event["symbol"],
                    dec(event["per_share"]),
                    event["pay_date"],
                    event_id=str(event["event_id"]),
                )
            else:
                raise ValueError("unsupported corporate action")
        opening = {symbol: dec(frame.loc[date, "open"]) for symbol, frame in bars.items()}
        closing = {symbol: dec(frame.loc[date, "close"]) for symbol, frame in bars.items()}
        pre_flow_equity = ledger.equity(opening) - flow
        if min(opening.values()) <= 0 or min(closing.values()) <= 0:
            raise ValueError("invalid prices")
        can_trade = all(
            bool(frame.loc[date].get("tradable", True))
            and float(frame.loc[date].get("volume", 1)) > 0
            for frame in bars.values()
        )
        if can_trade:
            if monthly_day:
                budget = max(ZERO, budget - min(tranche, budget))
            # Only settled cash can support an allocation; receivables are excluded.
            invested = sum((ledger.positions.get(s, ZERO) * p for s, p in opening.items()), ZERO)
            target_wealth = invested + max(ZERO, ledger.cash - budget - protected)
            targets = {symbol: target_wealth * dec(weight) for symbol, weight in weights.items()}
            if last_year is not None and date.year != last_year:
                for symbol, price in opening.items():
                    excess = ledger.positions.get(symbol, ZERO) * price - targets[symbol]
                    if excess > 0:
                        ledger.sell(
                            date, symbol, excess / price, price, lot, reason="annual_rebalance"
                        )
            # Purchases use current opening prices; no closing price enters the decision.
            for symbol, price in opening.items():
                shortage = targets[symbol] - ledger.positions.get(symbol, ZERO) * price
                available = max(ZERO, ledger.cash - budget - protected)
                if shortage > 0 and available:
                    ledger.buy(
                        date,
                        symbol,
                        min(shortage, available),
                        price,
                        lot,
                        reason="style_allocation",
                    )
        paid = ledger.settle(date, include_today=True)
        if not reinvest_dividends:
            protected += paid
        rows.append(
            {
                "date": date,
                "equity": float(ledger.equity(closing)),
                "cash": float(ledger.cash),
                "external_flow": float(flow),
                "pre_flow_equity": float(pre_flow_equity),
                "commission": float(ledger.commissions),
                "slippage": float(ledger.slippage),
                "gross_dividends": float(ledger.gross_dividends),
                "dividend_tax": float(ledger.dividend_tax),
                "turnover_notional": float(ledger.turnover_notional),
            }
        )
        last_month, last_year = month, date.year
    daily, journal = pd.DataFrame(rows).set_index("date"), pd.DataFrame(ledger.journal)
    return Backtest(
        daily,
        journal,
        performance(daily, journal),
        {
            "name": "style_annual_rebalance",
            "weights": weights,
            "initial": initial,
            "monthly": monthly,
            "tranches": tranches,
            "reinvest_dividends": reinvest_dividends,
        },
    )
