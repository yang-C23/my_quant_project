from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import backtrader as bt
import pandas as pd
import pytest

from quant.backtest.constraints import AShareConstraints
from quant.backtest.costs import AShareCommission, AShareCosts
from quant.backtest.feed import AShareDataFeed, build_feed

_FIXTURES = Path(__file__).parents[1] / "fixtures"


@dataclass
class _Line:
    value: float

    def __getitem__(self, index: int) -> float:
        assert index == 0
        return self.value


@dataclass
class _DateLine:
    value: pd.Timestamp

    def date(self, index: int) -> object:
        assert index == 0
        return self.value.date()


class _Bar:
    def __init__(self, row: pd.Series) -> None:
        self.datetime = _DateLine(pd.Timestamp(row.name))
        self.is_suspended = _Line(float(row["is_suspended"]))
        self.limit_up_price = _Line(float(row["limit_up_price"]))
        self.limit_down_price = _Line(float(row["limit_down_price"]))
        self.raw_open = _Line(float(row["raw_open"]))


def _bars() -> pd.DataFrame:
    frame = pd.read_csv(_FIXTURES / "bt_ashare_bars.csv", parse_dates=["date"])
    return frame.set_index("date")


def test_build_feed_merges_qfq_and_raw_flags_without_erasing_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = _bars()
    qfq = bars[["open", "high", "low", "close", "volume"]].copy()
    qfq.loc[pd.Timestamp("2023-09-07"), ["open", "high", "low", "close"]] = float("nan")
    raw = bars[["raw_open", "is_suspended", "limit_up_price", "limit_down_price"]].rename(
        columns={"raw_open": "open", "is_suspended": "suspended"}
    )
    calls: list[str] = []

    def fake_get_ohlcv(symbol: str, **kwargs: object) -> pd.DataFrame:
        assert symbol == "sh600000"
        calls.append(str(kwargs["adjust"]))
        return qfq if kwargs["adjust"] == "qfq" else raw

    monkeypatch.setattr("quant.backtest.feed.get_ohlcv", fake_get_ohlcv)
    feed = build_feed("sh600000", "2023-09-01", "2023-09-28")
    frame = feed.p.dataname

    assert calls == ["qfq", "raw"]
    assert frame.loc[pd.Timestamp("2023-09-07"), "open"] == 10.0
    assert frame.loc[pd.Timestamp("2023-09-07"), "volume"] == 0.0
    assert pd.isna(frame.loc[pd.Timestamp("2023-09-07"), "raw_open"])
    assert frame.loc[pd.Timestamp("2023-09-08"), "is_suspended"] == -1.0


def test_feed_exposes_all_raw_constraint_lines() -> None:
    seen: list[tuple[float, float, float, float]] = []

    class Capture(bt.Strategy):
        def next(self) -> None:
            seen.append(
                (
                    self.data.is_suspended[0],
                    self.data.limit_up_price[0],
                    self.data.limit_down_price[0],
                    self.data.raw_open[0],
                )
            )

    cerebro = bt.Cerebro()
    cerebro.adddata(AShareDataFeed(dataname=_bars()))
    cerebro.addstrategy(Capture)
    cerebro.run()

    assert seen[1] == (0.0, 11.0, 9.0, 11.0)
    assert seen[5][0] == -1.0


def test_constraints_pair_tplus_one_and_lot_rounding() -> None:
    bars = _bars()
    constraints = AShareConstraints()
    buy_day = _Bar(bars.loc[pd.Timestamp("2023-09-01")])
    next_day = _Bar(bars.loc[pd.Timestamp("2023-09-04")])

    assert constraints.can_buy(buy_day) is True
    constraints.on_buy_filled(pd.Timestamp("2023-09-01"), 100)
    assert constraints.can_sell(buy_day, 100) is False
    assert constraints.can_sell(next_day, 100) is True
    assert constraints.round_lots(150) == 100
    assert constraints.round_lots(99) == 0


def test_constraints_pair_limit_and_suspension_rejects_with_normal_passes() -> None:
    bars = _bars()
    constraints = AShareConstraints()
    normal = _Bar(bars.loc[pd.Timestamp("2023-09-01")])
    upper_limit = _Bar(bars.loc[pd.Timestamp("2023-09-04")])
    intraday_limit = _Bar(bars.loc[pd.Timestamp("2023-09-05")])
    unlocked_normal = _Bar(bars.loc[pd.Timestamp("2023-09-05")])
    lower_limit = _Bar(bars.loc[pd.Timestamp("2023-09-06")])
    suspended = _Bar(bars.loc[pd.Timestamp("2023-09-07")])

    assert constraints.can_buy(upper_limit) is False
    assert constraints.can_buy(intraday_limit) is True
    assert constraints.can_buy(suspended) is False
    assert constraints.can_buy(normal) is True

    constraints.on_buy_filled(pd.Timestamp("2023-09-01"), 100)
    assert constraints.can_sell(lower_limit, 100) is False
    assert constraints.can_sell(unlocked_normal, 100) is True
    assert constraints.can_sell(suspended, 100) is False


def test_constraints_reject_missing_flag_sentinel_for_both_sides() -> None:
    bars = _bars()
    constraints = AShareConstraints()
    constraints.on_buy_filled(pd.Timestamp("2023-09-01"), 100)
    missing_flag = _Bar(bars.loc[pd.Timestamp("2023-09-08")])

    assert missing_flag.is_suspended[0] == -1.0
    assert constraints.can_buy(missing_flag) is False
    assert constraints.can_sell(missing_flag, 100) is False


class _BuyAndHold(bt.Strategy):
    def next(self) -> None:
        if len(self) == 1:
            self.buy(size=100)


class _BuyThenSell(bt.Strategy):
    def next(self) -> None:
        if len(self) == 1:
            self.buy(size=100)
        elif len(self) == 3 and self.position:
            self.sell(size=100)


def _run_smoke(strategy: type[bt.Strategy]) -> float:
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(10000.0)
    cerebro.broker.addcommissioninfo(AShareCommission(AShareCosts()))
    cerebro.adddata(AShareDataFeed(dataname=_bars()))
    cerebro.addstrategy(strategy)
    cerebro.run()
    return cerebro.broker.getcash()


def test_cerebro_buy_hold_charges_minimum_commission_and_transfer_fee() -> None:
    # Initial 10,000.00 - 1,000.00 notional - 5.00 commission - 0.01 transfer = 8,994.99.
    assert round(_run_smoke(_BuyAndHold), 2) == 8994.99


def test_cerebro_sell_charges_stamp_tax_through_commission_bridge() -> None:
    # Buy cost is 1,000.00 + 5.00 + 0.01. Sell net is 1,000.00 - 5.00 - 0.01 - 0.50 stamp.
    # Final cash: 10,000.00 - 5.01 - 5.51 = 9,989.48.
    assert round(_run_smoke(_BuyThenSell), 2) == 9989.48
