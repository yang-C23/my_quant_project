from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from quant.longterm.engine import Strategy, run_strategy
from quant.longterm.features import (
    align_available,
    historical_percentile,
    price_features,
    select_etf,
)
from quant.longterm.ledger import Costs, Ledger, dec

FREE = Costs(dec(0), dec(0), dec(0), dec(0))


def bars(values, start="2020-01-02"):
    index = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame(
        {
            "open": values,
            "close": values,
            "high": np.array(values) * 1.01,
            "low": np.array(values) * 0.99,
        },
        index=index,
    )


def test_receivable_payment_split_and_withdrawal_hand_calculation():
    ledger = Ledger(FREE)
    ledger.deposit("2020-01-01", dec(1000))
    assert ledger.buy("2020-01-02", "ETF", dec(1000), dec(10)) == dec(100)
    ledger.dividend("2020-01-03", "ETF", dec(1), "2020-01-06", event_id="d1")
    assert ledger.cash == 0
    assert ledger.equity({"ETF": dec(9)}) == 1000
    assert ledger.buy("2020-01-03", "ETF", dec(100), dec(9)) == 0
    ledger.split("2020-01-06", "ETF", dec(2))
    assert ledger.equity({"ETF": dec("4.5")}) == 1000
    assert ledger.settle("2020-01-06", include_today=False) == 0
    assert ledger.settle("2020-01-06", include_today=True) == 100
    ledger.withdraw("2020-01-06", dec(100))
    assert ledger.contributions == ledger.equity({"ETF": dec("4.5")}) == 900


def test_deposits_do_not_create_return_and_next_session_only():
    data = bars([10.0] * 80)
    features = pd.DataFrame({"temperature": 0.9}, index=data.index)
    features.iloc[0, 0] = 0.1
    result = run_strategy(
        data,
        features,
        Strategy(name="valuation", initial=1200, monthly=100),
        symbol="ETF",
        costs=FREE,
    )
    # Day-1's cheap close cannot buy at day-1's open; first-of-month signal is high.
    assert result.metrics["trades"] == 0
    assert result.metrics["twr"] == 0
    assert result.metrics["xirr"] == pytest.approx(0, abs=1e-12)
    lump = run_strategy(
        data,
        features,
        Strategy(name="lump_sum", initial=1200, monthly=100),
        symbol="ETF",
        costs=FREE,
    )
    assert lump.metrics["contributed"] == result.metrics["contributed"]
    assert lump.metrics["ending_wealth"] == lump.metrics["contributed"]


def test_dividend_not_reinvested_until_after_payment_date():
    data = bars([10, 10, 9, 9, 9, 9, 9])
    actions = pd.DataFrame(
        [
            {
                "symbol": "ETF",
                "kind": "dividend",
                "event_id": "d",
                "ex_date": data.index[2],
                "pay_date": data.index[4],
                "per_share": 1,
            }
        ]
    )
    result = run_strategy(
        data,
        pd.DataFrame(index=data.index),
        Strategy(name="lump_sum", initial=1000, monthly=0),
        symbol="ETF",
        costs=FREE,
        actions=actions,
    )
    assert result.daily.iloc[2]["receivable"] == 100
    assert result.daily.iloc[4]["cash"] == 100
    assert result.daily.iloc[4]["shares"] == 100
    assert result.daily.iloc[5]["shares"] > 111
    assert result.metrics["twr"] == pytest.approx(0, abs=1e-8)
    with pytest.raises(ValueError, match="adjusted"):
        run_strategy(
            data,
            pd.DataFrame(index=data.index),
            Strategy(),
            symbol="ETF",
            actions=actions,
            price_basis="total_return",
        )


def test_percentile_warmup_ties_invalid_and_future_append():
    dates = pd.bdate_range("2000-01-01", periods=600)
    values = pd.Series(10.0, index=dates)
    result = historical_percentile(values, years=1)
    assert result.iloc[:250].isna().all()
    assert result.iloc[-1] == 0.5
    values.iloc[-1] = -1
    assert pd.isna(historical_percentile(values, years=1).iloc[-1])
    pd.testing.assert_series_equal(
        result.iloc[:400], historical_percentile(values.iloc[:400], years=1)
    )


def test_price_features_are_causal_and_close_only_has_no_kdj():
    rng = np.random.default_rng(7)
    data = bars(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 500))))
    pd.testing.assert_frame_equal(price_features(data).iloc[:350], price_features(data.iloc[:350]))
    assert price_features(data[["close"]])["j"].isna().all()


def test_asof_observations_not_released_are_invisible():
    frame = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-02"],
            "available_at": ["2020-01-03T12:00Z", "2020-01-04T12:00Z"],
            "pe": [10, 20],
        }
    )
    dates = pd.to_datetime(["2020-01-02T20:00Z", "2020-01-03T20:00Z"])
    values = align_available(frame, dates, "pe")
    assert pd.isna(values.iloc[0]) and values.iloc[1] == 10


def test_historical_etf_selection_ignores_future_winner():
    dates = pd.bdate_range("2020-01-01", periods=61)
    data = pd.DataFrame(
        [
            {
                "date": d,
                "symbol": s,
                "index_id": "X",
                "amount": a,
                "leveraged": False,
                "listed_at": dates[0],
            }
            for s, a in [("old", 100), ("other", 50)]
            for d in dates
        ]
    )
    data.loc[(data.symbol == "other") & (data.date == dates[-1]), "amount"] = 1e9
    assert select_etf(data, str(dates[-1].date()), "X") == "old"


def test_exit_tiers_locked_shares_and_core_protection():
    data = bars([10.0] * 160)
    features = pd.DataFrame({"temperature": 0.1}, index=data.index)
    # Complete initial 1-tranche investment, then tiered full liquidation.
    features.loc[features.index >= "2020-02-01", "temperature"] = 0.96
    result = run_strategy(
        data,
        features,
        Strategy(
            name="valuation",
            initial=1000,
            monthly=0,
            tranches=1,
            core_fraction=0.5,
            exit_style="tiers",
        ),
        symbol="ETF",
        costs=FREE,
    )
    assert result.daily.iloc[-1]["shares"] == 50
    assert result.daily.iloc[-1]["cash"] == 500
    assert result.metrics["twr"] == 0


def test_execution_matches_backtrader_independent_broker():
    import backtrader as bt

    data = bars([10, 11, 12, 13])

    class Once(bt.Strategy):
        def next(self):
            if len(self) == 1:
                self.buy(size=10)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(Once)
    cerebro.adddata(bt.feeds.PandasData(dataname=data))
    cerebro.broker.setcash(1000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.run()
    ledger = Ledger(Costs(dec(".001"), dec(0), dec(0), dec(0)))
    ledger.deposit(data.index[0], dec(1000))
    assert ledger.buy(data.index[1], "ETF", dec("110.11"), dec(11)) == 10
    assert float(ledger.equity({"ETF": dec(13)})) == pytest.approx(cerebro.broker.getvalue())


def test_style_portfolio_funding_and_rebalancing_are_self_financing():
    from quant.longterm.allocation import run_allocation

    a = bars([10.0] * 280)
    b = bars([20.0] * 280)
    result = run_allocation(
        {"A": a, "B": b}, initial=1200, monthly=100, costs=FREE, lot=Decimal("0.000001")
    )
    assert result.metrics["twr"] == 0
    assert result.metrics["ending_wealth"] == result.metrics["contributed"]
    assert result.daily.cash.min() >= 0


def test_cost_minimum_is_not_charged_in_addition_to_percentage():
    ledger = Ledger(Costs(dec(".001"), dec(5), dec(0), dec(0)))
    ledger.deposit("2020-01-01", dec(1005))
    assert ledger.buy("2020-01-02", "ETF", dec(1005), dec(10)) == 100
    assert ledger.cash == 0 and ledger.commissions == 5


def test_exact_twr_values_overnight_gain_before_new_month_deposit():
    data = pd.DataFrame(
        {"open": [10.0, 20.0], "close": [10.0, 20.0]},
        index=pd.to_datetime(["2020-01-31", "2020-02-03"]),
    )
    result = run_strategy(
        data,
        pd.DataFrame(index=data.index),
        Strategy(name="lump_sum", initial=1000, monthly=1000),
        symbol="ETF",
        costs=FREE,
    )
    assert result.metrics["ending_wealth"] == 3000
    assert result.metrics["contributed"] == 2000
    assert result.metrics["twr"] == pytest.approx(1.0)


def test_continuous_panic_is_one_event_cluster():
    prices = np.r_[np.full(260, 100.0), 100 * 0.95 ** np.arange(1, 50)]
    features = price_features(bars(prices))
    assert features.panic.sum() > 20
    assert features.panic_event.sum() == 1


def test_time_exit_pauses_between_three_qualifying_months():
    data = bars([10.0] * 150, start="2020-01-01")
    features = pd.DataFrame({"temperature": 0.1}, index=data.index)
    features.loc[features.index >= "2020-02-01", "temperature"] = 0.85
    features.loc[
        (features.index >= "2020-03-01") & (features.index < "2020-03-30"), "temperature"
    ] = 0.5
    result = run_strategy(
        data,
        features,
        Strategy(name="valuation", initial=900, monthly=0, tranches=1, exit_style="time"),
        symbol="ETF",
        costs=FREE,
    )
    sales = result.journal[result.journal.kind == "sell"]
    assert len(sales) == 3
    assert [float(q) for q in sales.quantity] == [30.0, 30.0, 30.0]
    assert result.daily.iloc[-1].shares == 0
    assert result.metrics["twr"] == 0


def test_event_additions_consume_budget_and_obey_cooldown():
    data = bars([10.0] * 65)
    features = pd.DataFrame({"temperature": 0.1, "panic_event": True}, index=data.index)
    result = run_strategy(
        data, features, Strategy(name="panic", initial=1200, monthly=0), symbol="ETF", costs=FREE
    )
    events = result.journal[
        (result.journal.kind == "buy") & (result.journal.reason == "panic_addition")
    ]
    dates = [data.index.get_loc(date) for date in events.date]
    assert len(dates) >= 2 and all(b - a >= 20 for a, b in zip(dates, dates[1:]))
    assert all(result.daily.cash >= 0) and all(result.daily.remaining_budget >= 0)
    assert result.metrics["ending_wealth"] == 1200 and result.metrics["contributed"] == 1200


def test_duplicate_dividend_cannot_silently_double_income():
    ledger = Ledger(FREE)
    ledger.dividend("2020-01-01", "ETF", dec(1), "2020-01-02", event_id="same")
    with pytest.raises(ValueError, match="duplicate"):
        ledger.dividend("2020-01-01", "ETF", dec(1), "2020-01-02", event_id="same")


def test_old_period_revision_does_not_replace_latest_known_temperature():
    observed = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-02", "2020-01-01", "2020-01-02"],
            "available_at": [
                "2020-01-02T12:00Z",
                "2020-01-03T12:00Z",
                "2020-01-04T12:00Z",
                "2020-01-05T12:00Z",
            ],
            "pe": [10, 20, 12, 21],
        }
    )
    decisions = pd.date_range("2020-01-02T20:00Z", periods=4)
    values = align_available(observed, decisions, "pe")
    assert values.tolist() == [10, 20, 20, 21]
    before_revision = align_available(observed.iloc[:2], decisions[:2], "pe")
    pd.testing.assert_series_equal(values.iloc[:2], before_revision)
    with pytest.raises(ValueError, match="increasing"):
        align_available(observed, decisions[::-1], "pe")


def test_research_blocks_etf_raw_price_split_before_computing_performance(tmp_path):
    from pathlib import Path
    import yaml
    from quant.config import Settings, load_config
    from quant.data.snapshots import SnapshotStore
    from quant.longterm.research import run_research

    store = SnapshotStore(tmp_path)
    identifier, folder = store.create()
    (folder / "staging/daily").mkdir(parents=True)
    data = bars([1.5, 0.75, 0.76]).reset_index(names="date").assign(symbol="sh512890")
    data.to_parquet(folder / "staging/daily/part.parquet", index=False)
    store.seal(identifier, {"publication_status": "validated"})
    store.activate(identifier)
    config = load_config(Path(__file__).resolve().parents[2] / "configs/longterm.yaml")
    config["universe"] = [config["universe"][9]]
    config["style_pairs"], config["extensions"] = [], []
    path = tmp_path / "protocol.yaml"
    path.write_text(yaml.safe_dump(config))
    result = run_research(Settings(_env_file=None, data_root=tmp_path), path, exploratory=True)
    table = pd.read_parquet(Path(result["directory"]) / "results.parquet")
    assert set(table.status) == {"blocked"}
    assert table.reason.str.contains("corporate_actions_incomplete").all()
    assert "annualized_return" not in table
