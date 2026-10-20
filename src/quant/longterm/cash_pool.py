"""Versioned cash-pool investing; monthly savings never become stranded capital."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
import math

import numpy as np
import pandas as pd

from quant.longterm.engine import Backtest, Strategy, performance, run_strategy
from quant.longterm.ledger import Costs, Ledger, ZERO, dec, money

FINANCIAL_COLUMNS = [
    "equity",
    "cash",
    "external_flow",
    "pre_flow_equity",
    "shares",
    "receivable",
    "commission",
    "slippage",
    "gross_dividends",
    "dividend_tax",
    "turnover_notional",
]
FACTOR_COLUMNS = {
    "vix_relief": ["vix", "vix_percentile"],
    "margin_relief": ["margin_drawdown_12m", "margin_change_1m", "margin_prior_change_1m"],
    "position_relief": ["leveraged_long_percentile"],
    "external_event": ["external_evidence"],
}


@dataclass(frozen=True)
class PoolPolicy:
    """Frozen entry evidence, funding, execution and exit rules for one experiment."""

    entry: str = "valuation"
    exit: str = "valuation_time"
    initial: float = 100000
    monthly: float = 1000
    tranches: int = 12
    buy_threshold: float = 0.4
    sell_threshold: float = 0.8
    event_tranches: int = 0
    cooldown: int = 20
    core_fraction: float = 0
    cash_yield: float = 0
    reinvest_dividends: bool = True
    dynamic_deep_threshold: float | None = None
    version: str = "cash-pool-v1"

    def __post_init__(self) -> None:
        if self.entry not in {
            "never",
            "external_event",
            "unconditional",
            "valuation",
            "pressure",
            "stabilized",
            "relief",
            "vix_relief",
            "margin_relief",
            "position_relief",
            "value_pressure",
            "value_stabilized",
            "value_relief",
            "value_vix_relief",
            "kdj",
            "value_kdj",
        }:
            raise ValueError("unsupported entry evidence")
        if self.exit not in {"none", "valuation_time", "valuation_tiers", "recovery_time"}:
            raise ValueError("unsupported exit rule")
        values = (
            self.initial,
            self.monthly,
            self.buy_threshold,
            self.sell_threshold,
            self.core_fraction,
            self.cash_yield,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("policy values must be finite")
        if self.initial <= 0 or self.monthly < 0 or not 0 <= self.core_fraction < 1:
            raise ValueError("positive initial capital, nonnegative saving and core < 1 required")
        if self.tranches < 1 or self.event_tranches < 0 or self.cooldown < 1:
            raise ValueError("positive batch count/cooldown required")
        if not 0 < self.buy_threshold < self.sell_threshold < 0.9 or self.cash_yield <= -1:
            raise ValueError("invalid thresholds or cash yield")
        if self.dynamic_deep_threshold is not None and not (
            0 < self.dynamic_deep_threshold < self.buy_threshold
        ):
            raise ValueError("deep valuation threshold must be below the buy threshold")

    @property
    def uses_value(self) -> bool:
        return self.entry == "valuation" or self.entry.startswith("value_")

    @property
    def event_column(self) -> str | None:
        name = self.entry.removeprefix("value_")
        return (
            name
            if name
            in {
                "pressure",
                "stabilized",
                "relief",
                "vix_relief",
                "margin_relief",
                "position_relief",
                "external_event",
            }
            else None
        )


def _flag(signal: dict, name: str) -> bool:
    value = signal.get(name)
    return value is not None and pd.notna(value) and bool(value)


def capital_metrics(daily: pd.DataFrame, journal: pd.DataFrame) -> dict:
    """Separate cash waiting and contributed-capital shortfall from peak drawdown."""
    deposits = daily["external_flow"].cumsum()
    short = daily["equity"] < deposits - 0.01
    worst_days, first_short = 0, None
    for date, below in short.items():
        if below and first_short is None:
            first_short = date
        if first_short is not None:
            worst_days = max(worst_days, (date - first_short).days)
            if not below:
                first_short = None
    buys = journal[journal["kind"].eq("buy")] if len(journal) else journal
    if "sleeve" in buys:
        buys = buys[buys["sleeve"].eq("tactical")]
    first_buy = pd.Timestamp(buys["date"].min()) if len(buys) else None
    start, end = daily.index[0], daily.index[-1]
    output = {
        "first_tactical_buy": str(first_buy.date()) if first_buy is not None else None,
        "initial_wait_days": (first_buy - start).days
        if first_buy is not None
        else (end - start).days,
        "initial_wait_censored": first_buy is None,
        "max_loss_vs_contributions": float((daily["equity"] / deposits - 1).min()),
        "longest_capital_shortfall_days": worst_days,
        "capital_shortfall_unrecovered": bool(short.iloc[-1]),
        "ending_profit": float(daily["equity"].iloc[-1] - deposits.iloc[-1]),
    }
    for months in (6, 12, 24):
        after = daily.loc[start + pd.DateOffset(months=months) :]
        output[f"cash_fraction_at_{months}m"] = (
            float(after.iloc[0]["cash"] / after.iloc[0]["equity"]) if len(after) else None
        )
        output[f"below_contributions_at_{months}m"] = (
            bool(short.loc[after.index[0]]) if len(after) else None
        )
    return output


def run_cash_pool(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    policy: PoolPolicy,
    *,
    symbol: str,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    costs: Costs | None = None,
    lot: Decimal = Decimal("0.000001"),
    actions: pd.DataFrame | None = None,
    price_basis: str = "raw",
    execution: str = "next_close",
) -> Backtest:
    """Use prior-session evidence and spend C/r of all settled tactical cash.

    Entry is immediate on a valid trigger; later batches execute monthly while
    eligibility remains valid. Pressure entries open a cycle, not an unconditional
    permanent saving plan. Extra event batches are a separate experimental axis.
    Exits execute on eligible monthly sessions; pending signals never borrow
    future deposits. Dividend cash becomes available only after the pay date.
    """
    column = {"next_open": "open", "next_close": "close"}.get(execution)
    if column is None or not {column, "close"}.issubset(bars):
        raise ValueError("execution requires actual prices")
    if (
        not bars.index.is_monotonic_increasing
        or not bars.index.is_unique
        or not bars.index.equals(features.index)
    ):
        raise ValueError("unique increasing bars and aligned features required")
    prices = bars[[column, "close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("positive finite prices required")
    if actions is not None and len(actions) and price_basis != "raw":
        raise ValueError("adjusted prices cannot receive company actions again")
    if policy.uses_value or policy.exit.startswith("valuation"):
        if "temperature" not in features:
            raise ValueError("valuation policy requires an explicit temperature series")
    required = policy.event_column
    if required is not None and required not in features:
        raise ValueError(f"missing stage evidence: {required}")
    if required is not None and policy.uses_value and "event_value_eligible" not in features:
        raise ValueError("value-stage entry requires valuation qualification at the pressure event")
    if policy.entry.endswith("kdj") and "j" not in features:
        raise ValueError("KDJ requires actual OHLC-derived J")

    if policy.core_fraction:
        fraction = policy.core_fraction
        arguments = dict(
            symbol=symbol,
            start=start,
            end=end,
            costs=costs,
            lot=lot,
            actions=actions,
            price_basis=price_basis,
            execution=execution,
        )
        core = run_strategy(
            bars,
            features,
            Strategy(
                name="lump_sum",
                initial=policy.initial * fraction,
                monthly=policy.monthly * fraction,
                cash_yield=policy.cash_yield,
                reinvest_dividends=policy.reinvest_dividends,
            ),
            **arguments,
        )
        tactical = run_cash_pool(
            bars,
            features,
            replace(
                policy,
                initial=policy.initial * (1 - fraction),
                monthly=policy.monthly * (1 - fraction),
                core_fraction=0,
            ),
            **arguments,
        )
        daily = tactical.daily.copy()
        daily[FINANCIAL_COLUMNS] = core.daily[FINANCIAL_COLUMNS] + tactical.daily[FINANCIAL_COLUMNS]
        journal = pd.concat(
            [core.journal.assign(sleeve="core"), tactical.journal.assign(sleeve="tactical")],
            ignore_index=True,
        )
        metrics = performance(daily, journal) | capital_metrics(daily, journal)
        metrics.update(execution=execution, price_basis=price_basis)
        return Backtest(daily, journal, metrics, asdict(policy))

    mask = np.ones(len(bars), dtype=bool)
    if start is not None:
        mask &= bars.index >= pd.Timestamp(start)
    if end is not None:
        mask &= bars.index <= pd.Timestamp(end)
    selected = np.flatnonzero(mask)
    if len(selected) < 2:
        raise ValueError("at least two sessions required")
    action_map = {}
    if actions is not None:
        if actions["event_id"].duplicated().any():
            raise ValueError("duplicate corporate action identifier")
        for action in actions.to_dict("records"):
            if action.get("symbol", symbol) != symbol:
                continue
            date = pd.Timestamp(action["ex_date"])
            if date not in bars.index or action["kind"] not in {"dividend", "split"}:
                raise ValueError("unsupported or missing-session company action")
            if action["kind"] == "dividend" and pd.isna(action.get("pay_date")):
                raise ValueError("verified dividend payment dates required")
            action_map.setdefault(date, []).append(action)
    ledger = Ledger(costs=costs or Costs())
    values = bars.to_dict("records")
    signals = features.to_dict("records")
    rows = []
    remaining, cycle, active = 0, 0, False
    locked, sold, exit_steps = ZERO, ZERO, 0
    anchor = math.nan
    previous_month, previous_date = None, None
    last_buy_month = None
    last_event = -policy.cooldown
    pending_trigger = None
    protected_dividends = ZERO
    for iteration, i in enumerate(selected):
        date = bars.index[i]
        bar = values[i]
        signal = signals[i - 1] if i else {}
        month = date.year, date.month
        monthly_day = month != previous_month
        external = (
            dec(policy.initial)
            if iteration == 0
            else (dec(policy.monthly) if monthly_day else ZERO)
        )
        if previous_date is not None and policy.cash_yield:
            interest = money(
                ledger.cash
                * dec((1 + policy.cash_yield) ** ((date - previous_date).days / 365.2425) - 1)
            )
            ledger.cash += interest
            ledger.record(date, "cash_interest", amount=interest)
        if external:
            ledger.deposit(date, external)
        paid = ledger.settle(date, include_today=False)
        if not policy.reinvest_dividends:
            protected_dividends += paid
        for action in action_map.get(date, []):
            if action["kind"] == "split":
                ratio = dec(action["ratio"])
                ledger.split(date, symbol, ratio)
                locked, sold = locked * ratio, sold * ratio
            else:
                ledger.dividend(
                    date,
                    symbol,
                    dec(action["per_share"]),
                    action["pay_date"],
                    event_id=str(action["event_id"]),
                )
        price = dec(bar[column])
        before_flow = ledger.equity({symbol: price}) - external
        tradable = pd.notna(bar.get("tradable", True)) and bool(bar.get("tradable", True))
        if "volume" in bar and (pd.isna(bar["volume"]) or bar["volume"] <= 0):
            tradable = False
        temperature = signal.get("temperature", math.nan)
        value_valid = pd.notna(temperature) and math.isfinite(float(temperature))
        cheap = value_valid and temperature < policy.buy_threshold
        gate = cheap if policy.uses_value else True
        if policy.entry == "never":
            gate = False
        if required in FACTOR_COLUMNS:
            gate = gate and all(pd.notna(signal.get(name)) for name in FACTOR_COLUMNS[required])
        if policy.entry.endswith("kdj"):
            gate = gate and pd.notna(signal.get("j")) and signal["j"] < 0
        if policy.exit.startswith("valuation") and not value_valid:
            # Missing valuation cannot justify fresh trades in either direction.
            gate = False
        pending_age = i - pending_trigger if pending_trigger is not None else 0
        if pending_age > policy.cooldown:
            pending_trigger = None
        pulse = _flag(signal, required) if required else False
        if required and policy.uses_value:
            pulse = pulse and _flag(signal, "event_value_eligible")
        trigger = pulse if required else gate
        if policy.entry.endswith("kdj"):
            trigger = trigger and monthly_day
        if gate and trigger:
            pending_trigger = i
        if not gate:
            pending_trigger = None

        # A cheap re-entry cancels the remainder of an old, partially executed exit.
        if sold > 0 and (cheap or (policy.exit == "recovery_time" and pulse and gate)):
            locked, sold, exit_steps = ZERO, ZERO, 0
            active, remaining = False, 0
            anchor = math.nan
        expensive = value_valid and temperature >= policy.sell_threshold
        recovered = math.isfinite(anchor) and signal.get("close", -math.inf) >= anchor
        exit_eligible = expensive if policy.exit.startswith("valuation") else recovered
        if policy.exit == "none":
            exit_eligible = False
        sold_today = False
        if monthly_day and exit_eligible and tradable:
            if locked == 0:
                locked = ledger.positions.get(symbol, ZERO)
                sold, exit_steps = ZERO, 0
            if locked:
                level = (
                    (3 if temperature >= 0.95 else 2 if temperature >= 0.90 else 1)
                    if policy.exit == "valuation_tiers"
                    else min(3, exit_steps + 1)
                )
                target = locked * dec(level) / 3
                actual = ledger.sell(
                    date, symbol, max(ZERO, target - sold), price, lot, reason=policy.exit
                )
                if actual:
                    sold += actual
                    exit_steps = level
                    sold_today = True
                    active, remaining, pending_trigger = False, 0, None
                    if ledger.positions.get(symbol, ZERO) == 0:
                        locked, sold, exit_steps = ZERO, ZERO, 0
                        anchor = math.nan
        first = (
            not active
            and pending_trigger is not None
            and gate
            and (cycle == 0 or month != last_buy_month or pulse)
        )
        event_add = (
            active
            and pulse
            and gate
            and i - last_event >= policy.cooldown
            and policy.event_tranches > 0
        )
        regular = active and gate and monthly_day and month != last_buy_month
        # Once an exit is armed, no buy may silently enlarge its locked position.
        can_buy = not sold_today and locked == 0 and tradable and gate
        used_batches = 0
        reason = "waiting"
        if can_buy and (first or regular or event_add):
            batches = policy.tranches if first else remaining
            count = 1 if first or regular else 0
            if pulse and i - last_event >= policy.cooldown:
                count += policy.event_tranches
            if (
                policy.dynamic_deep_threshold is not None
                and value_valid
                and temperature < policy.dynamic_deep_threshold
                and count
            ):
                count += 1
            count = min(count, batches)
            available = max(ZERO, ledger.cash - protected_dividends)
            spend = available * dec(count) / dec(batches) if batches else ZERO
            reason = (
                f"start_{policy.entry}"
                if first
                else ("event_addition" if event_add else "scheduled_pool")
            )
            quantity = ledger.buy(date, symbol, spend, price, lot, reason=reason) if spend else ZERO
            if quantity:
                if first:
                    cycle += 1
                    candidate = signal.get("event_anchor", signal.get("high_252", math.nan))
                    anchor = float(candidate) if pd.notna(candidate) else math.nan
                remaining = batches - count
                active = remaining > 0
                used_batches = count
                last_buy_month = month
                pending_trigger = None
                if pulse:
                    last_event = i
            else:
                reason = "insufficient_cash_or_lot"
        paid = ledger.settle(date, include_today=True)
        if not policy.reinvest_dividends:
            protected_dividends += paid
        equity = ledger.equity({symbol: dec(bar["close"])})
        rows.append(
            {
                "date": date,
                "equity": float(equity),
                "cash": float(ledger.cash),
                "external_flow": float(external),
                "pre_flow_equity": float(before_flow),
                "shares": float(ledger.positions.get(symbol, ZERO)),
                "receivable": float(sum((x["amount"] for x in ledger.receivables), ZERO)),
                "commission": float(ledger.commissions),
                "slippage": float(ledger.slippage),
                "gross_dividends": float(ledger.gross_dividends),
                "dividend_tax": float(ledger.dividend_tax),
                "turnover_notional": float(ledger.turnover_notional),
                "remaining_budget": float(max(ZERO, ledger.cash - protected_dividends)),
                "batches_remaining": remaining,
                "batches_executed": used_batches,
                "cycle": cycle,
                "locked_exit_shares": float(locked),
                "exit_sold_shares": float(sold),
                "valuation_eligible": bool(cheap),
                "entry_gate": bool(gate),
                "trigger": bool(pulse),
                "stage": "exiting" if locked else "deploying" if active else "waiting",
                "decision": policy.exit if sold_today else reason,
            }
        )
        previous_month, previous_date = month, date
    daily = pd.DataFrame(rows).set_index("date")
    journal = pd.DataFrame(ledger.journal)
    metrics = performance(daily, journal) | capital_metrics(daily, journal)
    metrics.update(execution=execution, price_basis=price_basis)
    return Backtest(daily, journal, metrics, asdict(policy))
