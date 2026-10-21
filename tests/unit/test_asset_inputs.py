"""Economic split/dividend marks must not manufacture panic or account returns."""

import numpy as np
import pandas as pd
import pytest

from quant.longterm.asset_inputs import prepare_action_prices
from quant.longterm.action_audit import verify_action_ledger
from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.ledger import Costs, dec


def test_halted_split_uses_adjusted_mark_without_trading_fictitious_quote():
    dates = pd.bdate_range("2021-10-20", periods=4)
    bars = pd.DataFrame(
        {"close": [1.639, 1.639, 1.639, 0.8195], "volume": [100, 100, 0, 100]}, index=dates
    )
    action = pd.DataFrame(
        [{"symbol": "fund", "kind": "split", "ex_date": dates[2], "ratio": 2, "event_id": "split"}]
    )
    raw, signal, corrections = prepare_action_prices(bars, action)
    assert raw.close.tolist() == [1.639, 1.639, 0.8195, 0.8195]
    assert signal.close.tolist() == [1.639] * 4
    assert len(corrections) == 1 and raw.observed_close.iloc[2] == 1.639
    result = run_cash_pool(
        raw,
        signal,
        PoolPolicy(entry="unconditional", exit="none", tranches=1, monthly=0),
        symbol="fund",
        actions=action,
        costs=Costs(commission_rate=dec(0), slippage_bps=dec(0)),
    )
    assert result.daily.equity.tolist() == [100000.0] * 4
    assert result.daily.shares.iloc[-1] == result.daily.shares.iloc[0] * 2
    assert not (
        pd.to_datetime(result.journal.loc[result.journal.kind.eq("buy"), "date"]) == dates[2]
    ).any()


def test_dividend_price_gap_is_not_panic_and_future_actions_do_not_change_past_signals():
    dates = pd.bdate_range("2020-01-01", periods=6)
    bars = pd.DataFrame({"close": [10, 10, 8, 8, 8, 4], "volume": 100}, index=dates)
    actions = pd.DataFrame(
        [
            {
                "symbol": "fund",
                "kind": "dividend",
                "ex_date": dates[2],
                "pay_date": dates[4],
                "per_share": 2,
                "event_id": "dividend",
                "ratio": np.nan,
            },
            {
                "symbol": "fund",
                "kind": "split",
                "ex_date": dates[5],
                "pay_date": pd.NaT,
                "per_share": np.nan,
                "event_id": "split",
                "ratio": 2,
            },
        ]
    )
    _, full, corrections = prepare_action_prices(bars, actions)
    assert corrections.empty
    assert full.close.tolist() == pytest.approx([10] * 6)
    _, prefix, _ = prepare_action_prices(bars.iloc[:5], actions.iloc[:1])
    pd.testing.assert_frame_equal(full.iloc[:5], prefix)


@pytest.mark.parametrize("core", [0, 0.5])
def test_independent_action_oracle_checks_tax_payment_split_and_external_flows(core):
    dates = pd.bdate_range("2020-01-01", periods=160)
    close = np.full(160, 10.0)
    close[40:] = 8.0
    close[90:] = 4.0
    bars = pd.DataFrame({"close": close, "volume": 100}, index=dates)
    actions = pd.DataFrame(
        [
            {
                "symbol": "fund",
                "kind": "dividend",
                "ex_date": dates[40],
                "pay_date": dates[45],
                "per_share": 2.0,
                "event_id": "dividend",
                "ratio": np.nan,
            },
            {
                "symbol": "fund",
                "kind": "split",
                "ex_date": dates[90],
                "pay_date": pd.NaT,
                "per_share": np.nan,
                "event_id": "split",
                "ratio": 2.0,
            },
        ]
    )
    raw, signal, _ = prepare_action_prices(bars, actions)
    costs = Costs(commission_rate=dec("0.001"), dividend_tax_rate=dec("0.15"))
    result = run_cash_pool(
        raw,
        signal,
        PoolPolicy(entry="unconditional", exit="none", tranches=3, monthly=100, core_fraction=core),
        symbol="fund",
        actions=actions,
        costs=costs,
    )
    assert verify_action_ledger(result, raw.close, actions, costs)["ok"]
    target = result.journal.index[result.journal.kind.eq("dividend_receivable")][0]
    result.journal.loc[target, "amount"] += dec("0.01")
    with pytest.raises(AssertionError, match="dividend amount"):
        verify_action_ledger(result, raw.close, actions, costs)
