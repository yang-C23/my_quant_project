from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.research.trade_pairs import run_pair_study


def _prices() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=8, freq="D")
    return pd.DataFrame(
        {
            "symbol": ["sh600000"] * len(dates),
            "date": dates,
            "open": [10.0, 10.0, 11.0, 12.0, 9.0, 8.0, 13.0, 14.0],
            "high": [10.5, 11.0, 12.0, 12.5, 9.5, 8.5, 13.5, 14.5],
            "low": [9.5, 9.8, 10.5, 8.8, 8.5, 7.5, 12.5, 13.5],
            "close": [10.0, 10.8, 11.8, 9.0, 8.8, 8.2, 13.2, 14.2],
            "raw_open": [10.0, 10.0, 11.0, 12.0, 9.0, 8.0, 13.0, 14.0],
            "limit_up_price": [np.nan] * len(dates),
            "is_suspended": [False] * len(dates),
        }
    )


def _signal(date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"symbol": ["sh600000"], "date": [pd.Timestamp(date)], "sig": [True]}
    )


def test_pair_study_immediate_exit_and_mae_mfe() -> None:
    prices = _prices()
    result = run_pair_study(
        _signal("2020-01-01"),
        {"dead_cross": _signal("2020-01-02")},
        prices,
        max_hold=5,
    )

    trade = result.trades.iloc[0]
    assert trade["entry_date"] == pd.Timestamp("2020-01-02")
    assert trade["exit_date"] == pd.Timestamp("2020-01-03")
    assert trade["return"] == pytest.approx(0.10)
    assert trade["exit_reason"] == "dead_cross"
    assert trade["mae"] == pytest.approx(-0.02)
    assert trade["mfe"] == pytest.approx(0.10)


def test_pair_study_max_hold_truncates() -> None:
    result = run_pair_study(_signal("2020-01-01"), {}, _prices(), max_hold=2)

    trade = result.trades.iloc[0]
    assert trade["exit_signal_date"] == pd.Timestamp("2020-01-03")
    assert trade["exit_date"] == pd.Timestamp("2020-01-04")
    assert trade["exit_reason"] == "max_hold"


def test_stop_loss_has_priority_over_signal_same_day() -> None:
    result = run_pair_study(
        _signal("2020-01-01"),
        {"dead_cross": _signal("2020-01-04")},
        _prices(),
        max_hold=5,
        stop_loss=0.10,
    )

    trade = result.trades.iloc[0]
    assert trade["exit_signal_date"] == pd.Timestamp("2020-01-04")
    assert trade["exit_reason"] == "stop_loss"


def test_exit_suspension_defers_to_next_open() -> None:
    prices = _prices()
    prices.loc[prices["date"].eq(pd.Timestamp("2020-01-03")), "is_suspended"] = True
    result = run_pair_study(
        _signal("2020-01-01"),
        {"dead_cross": _signal("2020-01-02")},
        prices,
        max_hold=5,
    )

    trade = result.trades.iloc[0]
    assert trade["exit_signal_date"] == pd.Timestamp("2020-01-02")
    assert trade["exit_date"] == pd.Timestamp("2020-01-04")
    assert trade["return"] == pytest.approx(0.20)


def test_overlapping_entries_are_ignored_until_exit() -> None:
    entries = pd.DataFrame(
        {
            "symbol": ["sh600000", "sh600000"],
            "date": pd.to_datetime(["2020-01-01", "2020-01-02"]),
            "sig": [True, True],
        }
    )
    result = run_pair_study(entries, {"dead_cross": _signal("2020-01-03")}, _prices())

    assert len(result.trades) == 1


def test_entry_low_stop_triggers_only_when_broken() -> None:
    # entry 01-02 (low 9.8); 01-03 low 10.5 持有; 01-04 low 8.8 跌破 → 止损
    result = run_pair_study(
        _signal("2020-01-01"),
        {},
        _prices(),
        max_hold=6,
        stop_loss="entry_low",
        two_day_no_profit=True,
    )

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_signal_date"] == pd.Timestamp("2020-01-04")
    assert trade["exit_date"] == pd.Timestamp("2020-01-05")


def test_entry_low_stop_never_fires_on_entry_day_itself() -> None:
    # entry 01-06 (low 7.5)，其后低点均高于 7.5 → 不得因 low<=own low 恒真而当日止损
    result = run_pair_study(
        _signal("2020-01-05"),
        {},
        _prices(),
        max_hold=6,
        stop_loss="entry_low",
        two_day_no_profit=False,
    )

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "max_hold"
    assert trade["hold_days"] == 2


def test_two_day_no_profit_exit_without_stop() -> None:
    result = run_pair_study(
        _signal("2020-01-02"),
        {},
        _prices(),
        max_hold=6,
        two_day_no_profit=True,
    )

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "two_day_no_profit"
    assert trade["exit_signal_date"] == pd.Timestamp("2020-01-05")


def test_stop_exit_defers_when_next_open_is_limit_down() -> None:
    prices = _prices()
    prices["limit_down_price"] = np.nan
    prices.loc[prices["date"].eq(pd.Timestamp("2020-01-05")), "limit_down_price"] = 9.0
    result = run_pair_study(
        _signal("2020-01-01"),
        {},
        prices,
        max_hold=6,
        stop_loss=0.10,
    )

    trade = result.trades.iloc[0]
    assert trade["exit_signal_date"] == pd.Timestamp("2020-01-04")
    assert trade["exit_date"] == pd.Timestamp("2020-01-06")
