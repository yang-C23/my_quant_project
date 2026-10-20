from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.diagnostics import verify_price_ledger
from quant.longterm.ledger import Costs, dec

FREE = Costs(dec(0), dec(0), dec(0), dec(0))


def inputs(dates, temperatures=None):
    dates = pd.to_datetime(dates)
    bars = pd.DataFrame({"close": 10.0, "open": 10.0}, index=dates)
    features = pd.DataFrame(index=dates)
    if temperatures is not None:
        features["temperature"] = temperatures
    features["close"] = 10.0
    return bars, features


def test_accumulated_savings_enter_the_cash_pool_hand_calculation():
    bars, features = inputs(
        [
            "2019-12-31",
            "2020-01-02",
            "2020-01-31",
            "2020-02-03",
            "2020-02-28",
            "2020-03-02",
            "2020-03-31",
            "2020-04-01",
        ],
        [0.5, 0.5, 0.5, 0.5, 0.2, 0.2, 0.2, 0.2],
    )
    result = run_cash_pool(
        bars,
        features,
        PoolPolicy(initial=1200, monthly=100, tranches=2, exit="none"),
        symbol="ETF",
        start="2020-01-02",
        costs=FREE,
    )
    # March: all 1400 accumulated cash / 2 = 700, not just the current month's saving.
    # April: remaining 700 + new 100, final batch spends all 800.
    assert result.daily.loc["2020-03-02", "cash"] == 700
    assert result.daily.loc["2020-04-01", "cash"] == 0
    assert result.daily.iloc[-1]["shares"] == 150
    assert result.metrics["contributed"] == result.metrics["ending_wealth"] == 1500
    assert result.metrics["twr"] == 0
    assert verify_price_ledger(result, bars["close"])["ok"]


def test_pause_then_resume_recomputes_all_cash_over_remaining_batches():
    bars, features = inputs(
        [
            "2019-12-31",
            "2020-01-02",
            "2020-01-31",
            "2020-02-03",
            "2020-02-28",
            "2020-03-02",
            "2020-03-31",
            "2020-04-01",
        ],
        [0.2, 0.2, 0.6, 0.6, 0.2, 0.2, 0.2, 0.2],
    )
    result = run_cash_pool(
        bars,
        features,
        PoolPolicy(initial=1200, monthly=100, tranches=3, exit="none"),
        symbol="ETF",
        start="2020-01-02",
        costs=FREE,
    )
    assert result.daily.loc["2020-01-02", "cash"] == 800
    assert result.daily.loc["2020-02-03", "cash"] == 900
    assert result.daily.loc["2020-03-02", "cash"] == 500  # (900 + 100) / 2 invested
    assert result.daily.iloc[-1]["cash"] == 0
    assert result.metrics["ending_wealth"] == 1500


def test_cash_control_never_trades_even_when_all_signals_are_positive():
    bars, features = inputs(pd.bdate_range("2020-01-01", periods=100))
    features["pressure"] = True
    features["temperature"] = 0.01
    result = run_cash_pool(
        bars,
        features,
        PoolPolicy(entry="never", exit="none"),
        symbol="ETF",
        costs=FREE,
    )
    assert result.metrics["trades"] == 0
    assert result.metrics["ending_wealth"] == result.metrics["contributed"]
    assert result.metrics["annualized_return"] == 0
    assert result.metrics["max_drawdown"] == 0


def test_stale_required_factor_pauses_an_already_active_cycle():
    dates = pd.bdate_range("2020-01-01", "2020-03-03")
    bars, features = inputs(dates)
    features["vix_relief"] = False
    features.loc[dates[0], "vix_relief"] = True
    features["vix"], features["vix_percentile"] = 30.0, 0.9
    features.loc["2020-01-31":, "vix"] = np.nan
    result = run_cash_pool(
        bars,
        features,
        PoolPolicy(entry="vix_relief", exit="none", tranches=3),
        symbol="ETF",
        costs=FREE,
    )
    assert result.metrics["trades"] == 1
    assert result.daily.iloc[-1].batches_remaining == 2


@pytest.mark.parametrize("style", ["valuation_time", "valuation_tiers"])
def test_exit_lock_split_and_new_cycle(style):
    bars, features = inputs(
        [
            "2019-12-31",
            "2020-01-02",
            "2020-01-31",
            "2020-02-03",
            "2020-02-28",
            "2020-03-02",
            "2020-03-31",
            "2020-04-01",
            "2020-04-02",
        ],
        [0.2, 0.2, 0.8, 0.8, 0.9, 0.9, 0.95, 0.2, 0.2],
    )
    bars.loc["2020-03-02":, ["close", "open"]] = 5
    actions = pd.DataFrame(
        [
            {
                "ex_date": "2020-03-02",
                "kind": "split",
                "ratio": 2,
                "event_id": "split",
                "symbol": "ETF",
            }
        ]
    )
    result = run_cash_pool(
        bars,
        features,
        PoolPolicy(initial=1200, monthly=0, tranches=1, exit=style),
        symbol="ETF",
        start="2020-01-02",
        costs=FREE,
        actions=actions,
    )
    sells = result.journal[result.journal.kind.eq("sell")]
    assert list(sells["quantity"]) == [dec(40), dec(80), dec(80)]
    assert result.daily.loc["2020-04-01", "cash"] == 1200
    assert result.daily.loc["2020-04-02", "shares"] == 240
    assert result.metrics["twr"] == 0


def test_pressure_trigger_is_next_session_and_event_budget_is_capped():
    dates = pd.bdate_range("2020-01-02", periods=12)
    bars, features = inputs(dates)
    features["pressure"] = False
    features.loc[dates[3], "pressure"] = True
    features["event_anchor"] = 20.0
    result = run_cash_pool(
        bars,
        features,
        PoolPolicy(
            entry="pressure", exit="none", initial=1200, monthly=0, tranches=12, event_tranches=2
        ),
        symbol="ETF",
        costs=FREE,
    )
    buys = result.journal[result.journal.kind.eq("buy")]
    assert buys.iloc[0]["date"] == dates[4]
    assert buys.iloc[0]["notional"] == dec(300)  # base one + two event batches
    assert result.daily.iloc[4]["batches_remaining"] == 9
    all_in = run_cash_pool(
        bars,
        features,
        PoolPolicy(
            entry="pressure", exit="none", initial=1200, monthly=0, tranches=2, event_tranches=20
        ),
        symbol="ETF",
        costs=FREE,
    )
    assert all_in.daily["cash"].min() == 0
    assert all_in.daily.iloc[4]["batches_remaining"] == 0
    assert all_in.metrics["trades"] == 1


def test_unfilled_order_preserves_batch_and_pending_signal():
    dates = pd.bdate_range("2020-01-02", periods=10)
    bars, features = inputs(dates)
    features["pressure"] = False
    features.loc[dates[1], "pressure"] = True
    bars["tradable"] = True
    bars.loc[dates[2], "tradable"] = False
    result = run_cash_pool(
        bars,
        features,
        PoolPolicy(entry="pressure", exit="none", initial=1200, monthly=0, tranches=2),
        symbol="ETF",
        costs=FREE,
    )
    buys = result.journal[result.journal.kind.eq("buy")]
    assert buys.iloc[0]["date"] == dates[3]
    assert result.daily.loc[dates[2], "batches_executed"] == 0
    assert result.daily.loc[dates[3], "batches_remaining"] == 1


def test_missing_valuation_never_becomes_permission_to_trade():
    dates = pd.bdate_range("2020-01-02", periods=40)
    bars, features = inputs(dates, [np.nan] * len(dates))
    result = run_cash_pool(bars, features, PoolPolicy(), symbol="ETF", costs=FREE)
    assert result.metrics["trades"] == 0
    assert result.metrics["twr"] == 0
    with pytest.raises(ValueError, match="temperature"):
        run_cash_pool(bars, features.drop(columns="temperature"), PoolPolicy(), symbol="ETF")


@pytest.mark.parametrize("core", [0, 0.25, 0.5])
def test_future_append_does_not_change_past_journal_and_funding(core):
    rng = np.random.default_rng(9)
    dates = pd.bdate_range("2019-12-31", periods=400)
    bars, features = inputs(dates, rng.uniform(0, 1, len(dates)))
    bars["close"] = 10 * np.exp(np.cumsum(rng.normal(0, 0.005, len(bars))))
    policy = PoolPolicy(core_fraction=core, tranches=6)
    whole = run_cash_pool(bars, features, policy, symbol="ETF")
    prefix = run_cash_pool(bars.iloc[:200], features.iloc[:200], policy, symbol="ETF")
    pd.testing.assert_frame_equal(whole.daily.iloc[:200], prefix.daily)
    old = whole.journal[pd.to_datetime(whole.journal.date) <= dates[199]]
    pd.testing.assert_frame_equal(old.reset_index(drop=True), prefix.journal.reset_index(drop=True))
    assert verify_price_ledger(whole, bars["close"])["ok"]
    assert whole.daily["cash"].min() >= 0
    other = run_cash_pool(
        bars, features, replace(policy, entry="unconditional", exit="none"), symbol="ETF"
    )
    pd.testing.assert_series_equal(whole.daily.external_flow, other.daily.external_flow)


def test_dividend_receivable_cannot_fund_entry_before_payment():
    dates = pd.bdate_range("2020-01-02", periods=8)
    bars, features = inputs(dates, [0.2] * len(dates))
    bars.loc[dates[2] :, ["close", "open"]] = 9.0
    actions = pd.DataFrame(
        [
            {
                "ex_date": dates[2],
                "kind": "dividend",
                "per_share": 1,
                "event_id": "div",
                "pay_date": dates[5],
                "symbol": "ETF",
            }
        ]
    )
    result = run_cash_pool(
        bars,
        features,
        PoolPolicy(initial=1200, monthly=0, tranches=1, exit="none"),
        symbol="ETF",
        costs=FREE,
        actions=actions,
    )
    assert result.daily.iloc[2]["receivable"] == 120
    assert result.daily.iloc[4]["cash"] == 0
    assert result.daily.iloc[5]["cash"] == 120
    assert result.metrics["twr"] == 0
    cash_div = run_cash_pool(
        bars,
        features,
        PoolPolicy(initial=1200, monthly=0, tranches=1, exit="none", reinvest_dividends=False),
        symbol="ETF",
        costs=FREE,
        actions=actions,
    )
    assert cash_div.metrics["ending_wealth"] == 1200
    assert cash_div.daily.iloc[-1]["cash"] == 120
