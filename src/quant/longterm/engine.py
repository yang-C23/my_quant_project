"""Deterministic next-session investment strategies over a real cash ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
import math

import numpy as np
import pandas as pd

from quant.backtest.metrics import geometric_metrics, xirr
from quant.longterm.ledger import Costs, Ledger, ZERO, dec, money


@dataclass(frozen=True)
class Strategy:
    """A frozen experiment, independent of data loading and model selection."""

    name: str = "dca"
    initial: float = 100000
    monthly: float = 1000
    tranches: int = 12
    buy_threshold: float = 0.4
    sell_threshold: float = 0.8
    exit_style: str = "time"
    event_tranches: int = 2
    cooldown: int = 20
    core_fraction: float = 0.0
    cash_yield: float = 0.0
    reinvest_dividends: bool = True

    def __post_init__(self) -> None:
        supported = {"lump_sum", "dca", "valuation", "panic", "stabilized", "kdj", "value_kdj"}
        if self.name not in supported or self.exit_style not in {"time", "tiers"}:
            raise ValueError("unknown strategy/exit")
        if self.initial < 0 or self.monthly < 0 or self.initial + self.monthly <= 0:
            raise ValueError("positive funding required")
        if self.tranches < 1 or self.event_tranches < 0 or self.cooldown < 1:
            raise ValueError("invalid funding schedule")
        if not 0 <= self.core_fraction <= 1 or not 0 < self.buy_threshold < self.sell_threshold < 1:
            raise ValueError("invalid core allocation or thresholds")
        if self.cash_yield <= -1:
            raise ValueError("invalid annual cash return")


@dataclass
class Backtest:
    """Full evidence, not only the best scalar statistic."""

    daily: pd.DataFrame
    journal: pd.DataFrame
    metrics: dict
    config: dict


def performance(daily: pd.DataFrame, journal: pd.DataFrame) -> dict:
    """TWR around the configured execution-time flows; XIRR from dated contributions."""
    previous = daily["equity"].shift(1).fillna(0)
    before_flow = daily["pre_flow_equity"]
    after_flow = before_flow + daily["external_flow"]
    # Value immediately before each external flow; chain overnight and intraday.
    before_factor = (before_flow / previous).where(previous > 0, 1.0)
    after_factor = (daily["equity"] / after_flow).where(after_flow > 0, 1.0)
    returns = before_factor * after_factor - 1
    metrics = geometric_metrics(returns)
    elapsed = max(1, (daily.index[-1] - daily.index[0]).days)
    total = float((1 + returns).prod())
    metrics["annualized_return"] = total ** (365.2425 / elapsed) - 1
    flows = [(date, -float(amount)) for date, amount in daily["external_flow"].items() if amount]
    flows.append((daily.index[-1], float(daily["equity"].iloc[-1])))
    metrics.update(
        twr=total - 1,
        xirr=xirr(flows),
        contributed=float(daily["external_flow"].sum()),
        ending_wealth=float(daily["equity"].iloc[-1]),
        ending_cash=float(daily["cash"].iloc[-1]),
        average_cash_fraction=float((daily["cash"] / daily["equity"]).mean()),
        sessions=len(daily),
        start=str(daily.index[0].date()),
        end=str(daily.index[-1].date()),
        commission=float(daily["commission"].iloc[-1]),
        slippage=float(daily["slippage"].iloc[-1]),
        gross_dividends=float(daily["gross_dividends"].iloc[-1]),
        dividend_tax=float(daily["dividend_tax"].iloc[-1]),
        turnover=float(daily["turnover_notional"].iloc[-1] / daily["equity"].mean()),
        trades=int(journal["kind"].isin(["buy", "sell"]).sum()) if len(journal) else 0,
    )
    daily["twr_return"] = returns
    daily["twr_nav"] = (1 + returns).cumprod()
    return metrics


def run_strategy(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    strategy: Strategy,
    *,
    symbol: str,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    costs: Costs | None = None,
    lot: Decimal = Decimal("0.000001"),
    actions: pd.DataFrame | None = None,
    price_basis: str = "raw",
    execution: str = "next_open",
) -> Backtest:
    """Run raw prices + actions, or an explicitly labelled price/total-return proxy.

    Decisions use features from the preceding recorded trading session. Initial
    and monthly funding is common to every strategy, including waiting cash.
    """
    if actions is not None and len(actions) and price_basis != "raw":
        raise ValueError("corporate actions cannot be added to adjusted/total-return prices")
    if execution not in {"next_open", "next_close"}:
        raise ValueError("unsupported execution convention")
    column = "open" if execution == "next_open" else "close"
    if column not in bars or "close" not in bars or not bars.index.is_unique:
        raise ValueError("execution prices and unique dates are required")
    if not bars.index.is_monotonic_increasing or not features.index.equals(bars.index):
        raise ValueError("features and bars must share the same increasing calendar")
    if (~np.isfinite(bars[[column, "close"]])).any().any() or (
        bars[[column, "close"]] <= 0
    ).any().any():
        raise ValueError("invalid execution prices")
    if not 0 <= strategy.core_fraction <= 1:
        raise ValueError("invalid core fraction")
    if strategy.core_fraction:
        fraction = strategy.core_fraction
        core = run_strategy(
            bars,
            features,
            replace(
                strategy,
                name="lump_sum",
                core_fraction=0,
                initial=strategy.initial * fraction,
                monthly=strategy.monthly * fraction,
            ),
            symbol=symbol,
            start=start,
            end=end,
            costs=costs,
            lot=lot,
            actions=actions,
            price_basis=price_basis,
            execution=execution,
        )
        if fraction == 1:
            return core
        tactical = run_strategy(
            bars,
            features,
            replace(
                strategy,
                core_fraction=0,
                initial=strategy.initial * (1 - fraction),
                monthly=strategy.monthly * (1 - fraction),
            ),
            symbol=symbol,
            start=start,
            end=end,
            costs=costs,
            lot=lot,
            actions=actions,
            price_basis=price_basis,
            execution=execution,
        )
        columns = [c for c in core.daily if c not in {"twr_return", "twr_nav"}]
        combined = core.daily[columns] + tactical.daily[columns]
        trades = pd.concat(
            [core.journal.assign(sleeve="core"), tactical.journal.assign(sleeve="tactical")],
            ignore_index=True,
        )
        return Backtest(combined, trades, performance(combined, trades), asdict(strategy))
    mask = pd.Series(True, index=bars.index)
    if start is not None:
        mask &= bars.index >= pd.Timestamp(start)
    if end is not None:
        mask &= bars.index <= pd.Timestamp(end)
    selected = np.flatnonzero(mask.to_numpy())
    if len(selected) < 2:
        raise ValueError("at least two sessions are required")
    ledger = Ledger(costs=costs or Costs())
    action_map = {}
    if actions is not None:
        for action in actions.to_dict("records"):
            if action.get("symbol", symbol) != symbol:
                continue
            date = pd.Timestamp(action["ex_date"])
            if date not in bars.index:
                raise ValueError("corporate action ex-date missing from trading calendar")
            if action["kind"] == "dividend" and pd.isna(action.get("pay_date")):
                raise ValueError("cash-ledger dividends require actual pay dates")
            action_map.setdefault(date, []).append(action)
    rows = []
    budget = dec(strategy.initial)
    tranche = budget / strategy.tranches
    started, had_exit = strategy.name in {"dca", "lump_sum"}, False
    locked, sold, time_steps = ZERO, ZERO, 0
    last_event = -strategy.cooldown
    previous_month = None
    previous_date = None
    reinvest_pending = ZERO
    protected_dividends = ZERO
    for iteration, index in enumerate(selected):
        date = bars.index[index]
        row = bars.iloc[index]
        signal = features.iloc[index - 1] if index > 0 else pd.Series(dtype=float)
        temperature = signal.get("temperature", math.nan)
        month = (date.year, date.month)
        monthly_day = month != previous_month
        monthly_flow = dec(strategy.monthly) if monthly_day and iteration > 0 else ZERO
        external = dec(strategy.initial) if iteration == 0 else monthly_flow
        if previous_date is not None and strategy.cash_yield:
            interest = money(
                ledger.cash
                * dec((1 + strategy.cash_yield) ** ((date - previous_date).days / 365.2425) - 1)
            )
            ledger.cash += interest
            ledger.record(date, "cash_interest", amount=interest)
        if external:
            ledger.deposit(date, external)
        paid = ledger.settle(date, include_today=False)
        reinvest_pending += paid
        protected_dividends += paid if not strategy.reinvest_dividends else ZERO
        for action in action_map.get(date, []):
            if action["kind"] == "split":
                ratio = dec(action["ratio"])
                ledger.split(date, symbol, ratio)
                locked, sold = locked * ratio, sold * ratio
            elif action["kind"] == "dividend":
                ledger.dividend(
                    date,
                    symbol,
                    dec(action["per_share"]),
                    action["pay_date"],
                    event_id=str(action["event_id"]),
                )
            else:
                raise ValueError(
                    "unsupported action; rights issues require a separate election model"
                )
        raw_price = dec(row[column])
        pre_flow_equity = ledger.equity({symbol: raw_price}) - external
        tradable = bool(row.get("tradable", True))
        if "volume" in bars and (pd.isna(row["volume"]) or row["volume"] <= 0):
            tradable = False
        cheap = pd.notna(temperature) and temperature < strategy.buy_threshold
        expensive = pd.notna(temperature) and temperature >= strategy.sell_threshold
        valuation = strategy.name in {"valuation", "panic", "stabilized", "value_kdj"}
        if cheap and had_exit:
            # Sales begin a fresh cycle. Accumulated cash is explicitly re-budgeted.
            budget = max(ZERO, ledger.cash - monthly_flow - protected_dividends)
            tranche = budget / strategy.tranches
            locked, sold, time_steps, had_exit = ZERO, ZERO, 0, False
            started = True
        if cheap and not started and valuation:
            started = True
        if valuation and expensive and monthly_day and tradable:
            if locked == 0:
                locked = ledger.positions.get(symbol, ZERO)
                sold, time_steps = ZERO, 0
            if locked:
                if strategy.exit_style == "time":
                    time_steps = min(3, time_steps + 1)
                    target = locked * dec(time_steps) / 3
                else:
                    level = 3 if temperature >= 0.95 else 2 if temperature >= 0.90 else 1
                    target = locked * dec(level) / 3
                quantity = max(ZERO, target - sold)
                actual = ledger.sell(
                    date, symbol, quantity, raw_price, lot, reason="high_valuation"
                )
                sold += actual
                had_exit |= actual > 0
        allowed = strategy.name in {"dca", "lump_sum"} or (valuation and cheap)
        if strategy.name in {"kdj", "value_kdj"}:
            allowed = bool(
                pd.notna(signal.get("j")) and signal["j"] < 0 and (strategy.name == "kdj" or cheap)
            )
        spend, principal_spend = ZERO, ZERO
        if monthly_day and allowed:
            principal_spend = budget if strategy.name == "lump_sum" else min(tranche, budget)
            spend = principal_spend + monthly_flow
        event_flag = "panic_event" if strategy.name == "panic" else "stabilized"
        event = (
            strategy.name in {"panic", "stabilized"}
            and cheap
            and bool(signal.get(event_flag, False))
            and index - last_event >= strategy.cooldown
        )
        if event:
            addition = min(tranche * strategy.event_tranches, max(ZERO, budget - principal_spend))
            spend += addition
            principal_spend += addition
        if strategy.name in {"lump_sum", "dca"} and strategy.reinvest_dividends:
            spend += reinvest_pending
        elif monthly_day and allowed and strategy.reinvest_dividends:
            # Tactical dividends remain in the cash pool and follow scheduled eligibility.
            spend += min(reinvest_pending, tranche)
        if spend and tradable:
            spend = min(spend, max(ZERO, ledger.cash - protected_dividends))
            before = ledger.cash
            quantity = ledger.buy(
                date,
                symbol,
                spend,
                raw_price,
                lot,
                reason="panic_addition" if event else "scheduled",
            )
            if quantity:
                used = before - ledger.cash
                used_principal = min(principal_spend, used)
                budget = max(ZERO, budget - used_principal)
                reinvest_pending = max(
                    ZERO, reinvest_pending - max(ZERO, used - used_principal - monthly_flow)
                )
                if event:
                    last_event = index
        paid = ledger.settle(date, include_today=True)
        reinvest_pending += paid
        protected_dividends += paid if not strategy.reinvest_dividends else ZERO
        equity = ledger.equity({symbol: dec(row["close"])})
        rows.append(
            {
                "date": date,
                "equity": float(equity),
                "cash": float(ledger.cash),
                "external_flow": float(external),
                "pre_flow_equity": float(pre_flow_equity),
                "shares": float(ledger.positions.get(symbol, ZERO)),
                "receivable": float(sum((r["amount"] for r in ledger.receivables), ZERO)),
                "commission": float(ledger.commissions),
                "slippage": float(ledger.slippage),
                "gross_dividends": float(ledger.gross_dividends),
                "dividend_tax": float(ledger.dividend_tax),
                "turnover_notional": float(ledger.turnover_notional),
                "remaining_budget": float(budget),
            }
        )
        previous_month, previous_date = month, date
    daily = pd.DataFrame(rows).set_index("date")
    journal = pd.DataFrame(ledger.journal)
    metrics = performance(daily, journal)
    metrics.update(execution=execution, price_basis=price_basis)
    return Backtest(daily, journal, metrics, asdict(strategy))
