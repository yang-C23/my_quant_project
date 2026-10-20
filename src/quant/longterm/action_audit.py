"""Independent ETF cash/entitlement reconstruction, without the trading ledger."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
import math

import pandas as pd

from quant.longterm.engine import Backtest
from quant.longterm.ledger import Costs


def verify_action_ledger(
    result: Backtest, close: pd.Series, actions: pd.DataFrame, costs: Costs
) -> dict:
    """Recompute entitlements from source notices and pre-ex-date holdings."""
    journal, daily = result.journal.copy(), result.daily
    allowed = {"deposit", "buy", "sell", "split", "dividend_receivable", "dividend_paid"}
    if not set(journal.kind).issubset(allowed):
        raise ValueError("unsupported event in company-action audit")
    journal["sleeve"] = journal.get("sleeve", "single")
    states = {
        key: {"cash": Decimal(0), "shares": Decimal(0), "due": {}}
        for key in journal.sleeve.unique()
    }
    action_map = {
        pd.Timestamp(date): frame.to_dict("records")
        for date, frame in actions.groupby("ex_date", sort=False)
    }
    groups = {pd.Timestamp(date): group for date, group in journal.groupby("date", sort=False)}
    units = Decimal(0)
    errors = dict.fromkeys(
        ("cash", "shares", "receivable", "equity", "pre_flow_equity", "external_flow", "nav"), 0.0
    )
    expected_entitlements, flows = 0, []

    def cents(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def account_value(price: Decimal) -> Decimal:
        return sum(
            (
                cents(
                    state["cash"]
                    + state["shares"] * price
                    + sum((x[1] for x in state["due"].values()), Decimal(0))
                )
                for state in states.values()
            ),
            Decimal(0),
        )

    for date, row in daily.iterrows():
        price = Decimal(str(close.loc[date]))
        group = groups.get(date, journal.iloc[:0])
        expected_paid = []
        for sleeve, state in states.items():
            for event_id, (pay_date, amount) in list(state["due"].items()):
                if pay_date < date:
                    state["cash"] += amount
                    del state["due"][event_id]
                    expected_paid.append((sleeve, event_id, amount))
            actual_actions = group[group.sleeve.eq(sleeve)]
            for action in action_map.get(date, []):
                if action["kind"] == "split":
                    ratio = Decimal(str(action["ratio"]))
                    matching = actual_actions[actual_actions.kind.eq("split")]
                    if len(matching) != 1 or Decimal(str(matching.iloc[0].ratio)) != ratio:
                        raise AssertionError("missing/incorrect split journal")
                    state["shares"] *= ratio
                else:
                    gross = cents(state["shares"] * Decimal(str(action["per_share"])))
                    tax = cents(gross * costs.dividend_tax_rate)
                    net = gross - tax
                    event_id = str(action["event_id"])
                    matching = actual_actions[
                        actual_actions.kind.eq("dividend_receivable")
                        & actual_actions.event_id.eq(event_id)
                    ]
                    if len(matching) != 1:
                        raise AssertionError("missing/duplicate dividend entitlement")
                    entry = matching.iloc[0]
                    if (entry.gross, entry.tax, entry.amount) != (gross, tax, net):
                        raise AssertionError("dividend amount disagrees with source terms/holdings")
                    state["due"][event_id] = (pd.Timestamp(action["pay_date"]), net)
                    expected_entitlements += 1
        before = account_value(price)
        contributions = group[group.kind.eq("deposit")]
        flow = sum(contributions.amount, Decimal(0))
        subscription_nav = before / units if units else Decimal(1)
        units += flow / subscription_nav
        for entry in contributions.to_dict("records"):
            states[entry["sleeve"]]["cash"] += entry["amount"]
        for entry in group[group.kind.isin(["buy", "sell"])].to_dict("records"):
            state = states[entry["sleeve"]]
            direction = 1 if entry["kind"] == "buy" else -1
            fill = price * (1 + direction * costs.slippage_bps / 10000)
            if entry["price"] != fill or cents(entry["quantity"] * fill) != entry["notional"]:
                raise AssertionError("execution price/notional mismatch")
            fee = cents(max(costs.minimum_commission, entry["notional"] * costs.commission_rate))
            if entry["fee"] != fee:
                raise AssertionError("commission mismatch")
            state["cash"] -= direction * entry["notional"] + fee
            state["shares"] += direction * entry["quantity"]
            if state["cash"] < 0 or state["shares"] < 0:
                raise AssertionError("spending unsettled money or selling unowned shares")
        for sleeve, state in states.items():
            for event_id, (pay_date, amount) in list(state["due"].items()):
                if pay_date == date:
                    state["cash"] += amount
                    del state["due"][event_id]
                    expected_paid.append((sleeve, event_id, amount))
        actual_paid = [
            (x["sleeve"], str(x["event_id"]), x["amount"])
            for x in group[group.kind.eq("dividend_paid")].to_dict("records")
        ]
        if sorted(expected_paid) != sorted(actual_paid):
            raise AssertionError("dividend became spendable on the wrong session")
        cash = sum((state["cash"] for state in states.values()), Decimal(0))
        shares = sum((state["shares"] for state in states.values()), Decimal(0))
        due = sum(
            (amount for state in states.values() for _, amount in state["due"].values()), Decimal(0)
        )
        equity = account_value(price)
        expected = dict(
            cash=cash,
            shares=shares,
            receivable=due,
            equity=equity,
            pre_flow_equity=before,
            external_flow=flow,
            nav=equity / units,
        )
        for key, value in expected.items():
            actual = row["twr_nav" if key == "nav" else key]
            error = abs(float(value) - actual)
            if key == "nav":
                error /= max(1, abs(float(value)))
            if not math.isfinite(error):
                raise AssertionError("nonfinite audit result")
            errors[key] = max(errors[key], error)
        if flow:
            flows.append((date, -float(flow)))
    flows.append((daily.index[-1], float(equity)))
    rate = result.metrics["xirr"]
    if rate is None or rate <= -1 or not math.isfinite(rate):
        raise AssertionError("unverifiable XIRR")
    residual = sum(
        amount / (1 + rate) ** ((date - flows[0][0]).days / 365.2425) for date, amount in flows
    )
    normalized = abs(residual) / sum(abs(amount) for _, amount in flows)
    if max(errors.values()) > 1e-8 or normalized > 1e-8:
        raise AssertionError(f"action ledger mismatch: {errors}, xirr={residual}")
    return {
        "ok": True,
        "maximum_errors": errors,
        "xirr_relative_residual": normalized,
        "entitlements_checked": expected_entitlements,
    }
