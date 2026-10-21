"""Portfolio tests use economic invariants, real entitlement timing and causal orders."""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from quant.longterm.ledger import Costs, dec
from quant.longterm.style_pool import run_style_pool, verify_style_ledger


FREE = Costs(dec(0), dec(0), dec(0))


def empty_actions():
    return pd.DataFrame(columns=["event_id", "ex_date", "kind"])


def test_style_pool_deposits_are_not_returns_and_halted_month_is_deferred():
    dates = pd.bdate_range("2020-01-01", "2021-03-01")
    bars = {
        s: pd.DataFrame({"close": p, "volume": 100}, index=dates)
        for s, p in (("A", 10.0), ("B", 20.0))
    }
    bars["A"].loc["2021-01-01", "volume"] = 0
    actions = dict.fromkeys(bars, empty_actions())
    result = run_style_pool(
        bars,
        actions,
        start=str(dates[0].date()),
        end=str(dates[-1].date()),
        initial=1200,
        monthly=120,
        tranches=3,
        costs=FREE,
        lot=Decimal(".000001"),
    )
    assert result.metrics["ending_wealth"] == result.metrics["contributed"]
    assert result.metrics["twr"] == pytest.approx(0)
    trades = result.journal[result.journal.kind.eq("buy")]
    assert not trades.date.eq(pd.Timestamp("2021-01-01")).any()
    assert trades.date.eq(pd.Timestamp("2021-01-04")).any()
    close = pd.DataFrame({s: b.close for s, b in bars.items()})
    assert verify_style_ledger(result, close, actions, FREE)["ok"]


def test_style_dividend_entitlement_and_future_append_do_not_create_profit():
    dates = pd.bdate_range("2020-01-01", periods=100)
    a = np.full(100, 10.0)
    a[40:] = 8
    bars = {
        s: pd.DataFrame({"close": p, "volume": 100}, index=dates)
        for s, p in (("A", a), ("B", 10.0))
    }
    actions = {
        "A": pd.DataFrame(
            [
                {
                    "event_id": "A_div",
                    "kind": "dividend",
                    "ex_date": dates[40],
                    "pay_date": dates[45],
                    "per_share": 2.0,
                }
            ]
        ),
        "B": empty_actions(),
    }
    kwargs = dict(
        start=str(dates[0].date()),
        end=str(dates[-1].date()),
        tranches=1,
        costs=FREE,
        lot=Decimal(".000001"),
    )
    result = run_style_pool(bars, actions, **kwargs)
    assert result.metrics["twr"] == pytest.approx(0, abs=1e-12)
    assert result.daily.loc[dates[40], "receivable"] > 0
    assert result.daily.loc[dates[44], "receivable"] == result.daily.loc[dates[40], "receivable"]
    assert result.daily.loc[dates[45], "receivable"] == 0
    close = pd.DataFrame({s: b.close for s, b in bars.items()})
    assert verify_style_ledger(result, close, actions, FREE)["ok"]
    prefix = run_style_pool(bars, actions, **(kwargs | {"end": str(dates[60].date())}))
    pd.testing.assert_frame_equal(prefix.daily, result.daily.loc[: dates[60]])


def test_annual_rebalance_quantity_cannot_see_same_day_price_jump():
    dates = pd.to_datetime(["2020-12-29", "2020-12-30", "2020-12-31", "2021-01-04", "2021-01-05"])
    bars = {
        "A": pd.DataFrame({"close": [10, 10, 10, 20, 20], "volume": 100}, index=dates),
        "B": pd.DataFrame({"close": 10, "volume": 100}, index=dates),
    }
    result = run_style_pool(
        bars,
        dict.fromkeys(bars, empty_actions()),
        start="2020-12-30",
        end="2021-01-05",
        monthly=0,
        tranches=1,
        costs=FREE,
    )
    assert not result.journal.kind.eq("sell").any()
    assert result.metrics["ending_wealth"] == 150000
