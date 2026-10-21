from copy import deepcopy

import pandas as pd
import pytest

from quant.longterm.diagnostics import drawdown_episode, verify_price_ledger
from quant.longterm.engine import Strategy, run_strategy
from quant.longterm.ledger import Costs, dec

FREE = Costs(dec(0), dec(0), dec(0), dec(0))


@pytest.mark.parametrize("core", [0, 0.5])
@pytest.mark.parametrize("bad_nav", [1.01, float("nan")])
def test_unitization_hand_example_and_tampering(core, bad_nav):
    # 100 buys 10 shares. At price 20, another 100 buys 5 shares; final value 150.
    # A fund issues 100 initial units, then 50 units at NAV 2; terminal NAV is 1.
    dates = pd.to_datetime(["2020-01-31", "2020-02-03", "2020-02-28"])
    bars = pd.DataFrame({"close": [10, 20, 10]}, index=dates)
    result = run_strategy(
        bars,
        pd.DataFrame(index=dates),
        Strategy(name="lump_sum", initial=100, monthly=100, core_fraction=core),
        symbol="test",
        costs=FREE,
        execution="next_close",
    )
    assert result.metrics["contributed"] == 200
    assert result.metrics["ending_wealth"] == 150
    assert result.metrics["twr"] == 0
    assert verify_price_ledger(result, bars["close"])["ok"]
    episode = drawdown_episode(result.daily["twr_nav"])
    assert episode["max_drawdown"] == -0.5
    assert episode["peak_date"] == "2020-02-03"
    assert episode["unrecovered"]
    corrupt = deepcopy(result)
    corrupt.daily.iloc[-1, corrupt.daily.columns.get_loc("twr_nav")] = bad_nav
    with pytest.raises(AssertionError, match="independent journal"):
        verify_price_ledger(corrupt, bars["close"])


def test_kdj_skipped_monthly_cash_is_not_rebudgeted_characterization():
    dates = pd.to_datetime(
        ["2019-12-31", "2020-01-02", "2020-01-31", "2020-02-03", "2020-02-28", "2020-03-02"]
    )
    bars = pd.DataFrame({"close": [10] * len(dates)}, index=dates)
    features = pd.DataFrame({"j": [-1, 1, 1, 1, -1, 1]}, index=dates)
    result = run_strategy(
        bars,
        features,
        Strategy(name="kdj", initial=1200, monthly=100),
        symbol="test",
        start="2020-01-02",
        costs=FREE,
        execution="next_close",
    )
    # January buys 100; February waits; March buys 100 principal + current 100.
    assert result.metrics["contributed"] == 1400
    assert result.daily.iloc[-1]["shares"] == 30
    assert result.daily.iloc[-1]["remaining_budget"] == 1000
    assert result.daily.iloc[-1]["cash"] == 1100
    assert verify_price_ledger(result, bars["close"])["ok"]


def test_drawdown_counts_initial_trading_cost_and_recovery():
    nav = pd.Series([0.99, 0.98, 1.0], index=pd.date_range("2020-01-01", periods=3))
    episode = drawdown_episode(nav)
    assert episode["max_drawdown"] == pytest.approx(-0.02)
    assert episode["peak_date"] is None  # pre-investment NAV 1, not a fictitious session
    assert episode["recovery_date"] == "2020-01-03"
