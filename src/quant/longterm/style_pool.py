"""Cash-pool style allocation with dated distributions and prior-close rebalance targets."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from quant.longterm.cash_pool import capital_metrics
from quant.longterm.engine import Backtest, performance
from quant.longterm.ledger import Costs, Ledger, ZERO, dec


def run_style_pool(
    bars: dict[str, pd.DataFrame],
    actions: dict[str, pd.DataFrame],
    *,
    start: str,
    end: str,
    initial: float = 100000,
    monthly: float = 1000,
    tranches: int = 12,
    annual_rebalance: bool = True,
    reinvest_dividends: bool = True,
    costs: Costs | None = None,
    lot: Decimal = Decimal("100"),
) -> Backtest:
    """Split each cash batch equally; annually rebalance using preceding-close weights.

    The account holds all waiting cash. Rebalance orders use prior marks adjusted
    for today's verified actions, then fill at today's close plus costs. Halted
    first-of-month/year sessions defer the pending operation instead of dropping it.
    This is a named, same-market product comparison, not historical ETF selection.
    """
    if len(bars) != 2 or set(bars) != set(actions):
        raise ValueError("two same-market funds and their reviewed actions required")
    if initial <= 0 or monthly < 0 or tranches < 1:
        raise ValueError("invalid contribution schedule")
    calendar = next(iter(bars.values())).index
    for frame in bars.values():
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError("unique ordered calendars required")
        calendar = calendar.intersection(frame.index)
        if not np.isfinite(frame.close).all() or (frame.close <= 0).any():
            raise ValueError("positive execution marks required")
    selected = np.flatnonzero((calendar >= pd.Timestamp(start)) & (calendar <= pd.Timestamp(end)))
    if len(selected) < 2:
        raise ValueError("insufficient common calendar")
    events = {}
    for symbol, frame in actions.items():
        if frame.event_id.duplicated().any():
            raise ValueError("duplicate corporate action")
        for action in frame.to_dict("records"):
            date = pd.Timestamp(action["ex_date"])
            if start <= str(date.date()) <= end and date not in calendar:
                raise ValueError("action missing from the shared calendar")
            events.setdefault(date, []).append({**action, "symbol": symbol})
    ledger = Ledger(costs=costs or Costs())
    remaining, protected = tranches, ZERO
    last_flow_month, last_buy_month, rebalanced_year = None, None, None
    rows = []
    for n, i in enumerate(selected):
        date = calendar[i]
        month = date.year, date.month
        flow = dec(initial) if n == 0 else dec(monthly) if month != last_flow_month else ZERO
        if flow:
            ledger.deposit(date, flow)
        paid = ledger.settle(date, include_today=False)
        if not reinvest_dividends:
            protected += paid
        previous = {
            symbol: dec(frame.at[calendar[max(0, i - 1)], "close"])
            for symbol, frame in bars.items()
        }
        for action in events.get(date, []):
            symbol = action["symbol"]
            if action["kind"] == "split":
                ledger.split(date, symbol, dec(action["ratio"]))
                previous[symbol] /= dec(action["ratio"])
            elif action["kind"] == "dividend":
                if pd.isna(action.get("pay_date")):
                    raise ValueError("verified dividend pay date required")
                ledger.dividend(
                    date,
                    symbol,
                    dec(action["per_share"]),
                    action["pay_date"],
                    event_id=action["event_id"],
                )
                previous[symbol] -= dec(action["per_share"])
            else:
                raise ValueError("unsupported action")
        prices = {symbol: dec(frame.at[date, "close"]) for symbol, frame in bars.items()}
        before_flow = ledger.equity(prices) - flow
        tradable = all(
            pd.notna(frame.loc[date].get("tradable", True))
            and bool(frame.loc[date].get("tradable", True))
            and frame.loc[date].get("volume", 1) > 0
            for frame in bars.values()
        )
        batch_due = month != last_buy_month
        rebalance_due = annual_rebalance and rebalanced_year != date.year
        executed = False
        if tradable and (batch_due or rebalance_due):
            count = remaining if remaining else tranches
            spend = max(ZERO, ledger.cash - protected) / count if batch_due else ZERO
            released = spend
            if rebalance_due and n:
                invested = sum(
                    (ledger.positions.get(s, ZERO) * price for s, price in previous.items()), ZERO
                )
                target = (invested + spend) / 2
                for symbol, price in previous.items():
                    if price <= 0:
                        raise ValueError("nonpositive prior action-adjusted mark")
                    excess = max(ZERO, ledger.positions.get(symbol, ZERO) * price - target)
                    cash_before = ledger.cash
                    ledger.sell(
                        date,
                        symbol,
                        excess / price,
                        prices[symbol],
                        lot,
                        reason="annual_prior_close_target",
                    )
                    released += ledger.cash - cash_before
                needs = {
                    s: max(ZERO, target - ledger.positions.get(s, ZERO) * price)
                    for s, price in previous.items()
                }
            else:
                needs = dict.fromkeys(bars, Decimal("0.5"))
            total_need = sum(needs.values(), ZERO)
            budgets = {
                s: released * need / total_need if total_need else ZERO for s, need in needs.items()
            }
            for symbol in bars:
                quantity = ledger.buy(
                    date,
                    symbol,
                    budgets[symbol],
                    prices[symbol],
                    lot,
                    reason="style_pool_batch" if batch_due else "annual_prior_close_target",
                )
                executed |= quantity > 0
            if executed and batch_due:
                remaining = count - 1
                last_buy_month = month
            if rebalance_due:
                rebalanced_year = date.year
        paid = ledger.settle(date, include_today=True)
        if not reinvest_dividends:
            protected += paid
        rows.append(
            {
                "date": date,
                "equity": float(ledger.equity(prices)),
                "cash": float(ledger.cash),
                "external_flow": float(flow),
                "pre_flow_equity": float(before_flow),
                "receivable": float(sum((x["amount"] for x in ledger.receivables), ZERO)),
                "commission": float(ledger.commissions),
                "slippage": float(ledger.slippage),
                "gross_dividends": float(ledger.gross_dividends),
                "dividend_tax": float(ledger.dividend_tax),
                "turnover_notional": float(ledger.turnover_notional),
                "batches_remaining": remaining,
                **{f"shares_{s}": float(ledger.positions.get(s, ZERO)) for s in bars},
            }
        )
        last_flow_month = month
    daily = pd.DataFrame(rows).set_index("date")
    journal = pd.DataFrame(ledger.journal)
    metrics = performance(daily, journal) | capital_metrics(daily, journal)
    return Backtest(
        daily,
        journal,
        metrics,
        {
            "version": "style-pool-v1",
            "weights": dict.fromkeys(bars, 0.5),
            "initial": initial,
            "monthly": monthly,
            "tranches": tranches,
            "annual_rebalance": annual_rebalance,
            "reinvest_dividends": reinvest_dividends,
            "execution": "next_close_prior_close_rebalance_targets",
        },
    )


def verify_style_ledger(
    result: Backtest,
    closes: pd.DataFrame,
    actions: dict[str, pd.DataFrame],
    costs: Costs,
) -> dict:
    """Independently reconstruct portfolio cash, entitlements, units and positions."""
    from decimal import ROUND_HALF_EVEN

    def cents(value: Decimal) -> Decimal:
        return value.quantize(Decimal(".01"), rounding=ROUND_HALF_EVEN)

    cash, units = Decimal(0), Decimal(0)
    positions = dict.fromkeys(closes, Decimal(0))
    due, events, flows = {}, {}, []
    groups = {pd.Timestamp(d): g for d, g in result.journal.groupby("date")}
    for symbol, frame in actions.items():
        for action in frame.to_dict("records"):
            events.setdefault(pd.Timestamp(action["ex_date"]), []).append(
                {**action, "symbol": symbol}
            )
    maximum_error = 0.0
    for date, row in result.daily.iterrows():
        group = groups.get(date, result.journal.iloc[:0])
        expected_paid = []
        for event_id, (pay, amount) in list(due.items()):
            if pay < date:
                cash += amount
                expected_paid.append((event_id, amount))
                del due[event_id]
        for action in events.get(date, []):
            symbol = action["symbol"]
            if action["kind"] == "split":
                positions[symbol] *= Decimal(str(action["ratio"]))
            else:
                gross = cents(positions[symbol] * Decimal(str(action["per_share"])))
                net = gross - cents(gross * costs.dividend_tax_rate)
                entries = group[group.kind.eq("dividend_receivable")]
                entries = entries[entries.event_id.eq(action["event_id"])]
                if len(entries) != 1 or entries.iloc[0].amount != net:
                    raise AssertionError("incorrect source-derived dividend entitlement")
                due[action["event_id"]] = pd.Timestamp(action["pay_date"]), net
        prices = {s: Decimal(str(closes.at[date, s])) for s in closes}

        def value() -> Decimal:
            return cents(
                cash
                + sum((positions[s] * prices[s] for s in closes), Decimal(0))
                + sum((x[1] for x in due.values()), Decimal(0))
            )

        before = value()
        flow = sum(group[group.kind.eq("deposit")].amount, Decimal(0))
        units += flow / (before / units if units else 1)
        cash += flow
        for entry in group[group.kind.isin(["buy", "sell"])].to_dict("records"):
            sign = 1 if entry["kind"] == "buy" else -1
            fill = prices[entry["symbol"]] * (1 + sign * costs.slippage_bps / 10000)
            notional = cents(entry["quantity"] * fill)
            fee = cents(max(costs.minimum_commission, notional * costs.commission_rate))
            if (entry["price"], entry["notional"], entry["fee"]) != (fill, notional, fee):
                raise AssertionError("incorrect fill or fee")
            cash -= sign * notional + fee
            positions[entry["symbol"]] += sign * entry["quantity"]
        for event_id, (pay, amount) in list(due.items()):
            if pay == date:
                cash += amount
                expected_paid.append((event_id, amount))
                del due[event_id]
        actual_paid = [
            (x["event_id"], x["amount"])
            for x in group[group.kind.eq("dividend_paid")].to_dict("records")
        ]
        if sorted(actual_paid) != sorted(expected_paid):
            raise AssertionError("wrong dividend settlement date")
        expected = {
            "equity": value(),
            "cash": cash,
            "external_flow": flow,
            "pre_flow_equity": before,
            "twr_nav": value() / units,
            "receivable": sum((x[1] for x in due.values()), Decimal(0)),
            **{f"shares_{s}": q for s, q in positions.items()},
        }
        for key, amount in expected.items():
            maximum_error = max(maximum_error, abs(float(amount) - row[key]))
        if cash < 0 or min(positions.values()) < 0:
            raise AssertionError("portfolio borrowed cash or shares")
        if flow:
            flows.append((date, -float(flow)))
    flows.append((date, float(value())))
    rate = result.metrics["xirr"]
    residual = sum(
        amount / (1 + rate) ** ((date - flows[0][0]).days / 365.2425) for date, amount in flows
    ) / sum(abs(amount) for _, amount in flows)
    if maximum_error > 1e-8 or abs(residual) > 1e-8:
        raise AssertionError(f"portfolio accounting mismatch: {maximum_error}, {residual}")
    return {"ok": True, "maximum_error": maximum_error, "xirr_relative_residual": abs(residual)}
