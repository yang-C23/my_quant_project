from __future__ import annotations

import numpy as np
import pandas as pd

from quant.research.forward_returns import run_event_study


def _prices() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=8, freq="D")
    rows = []
    for symbol, base in [("sh600000", 100.0), ("sz000001", 200.0), ("sh601318", 50.0)]:
        for i, date in enumerate(dates):
            rows.append(
                {
                    "symbol": symbol,
                    "date": date,
                    "open": base + i,
                    "close": base + i + 1.0,
                    "raw_open": base + i,
                    "limit_up_price": np.nan,
                    "is_suspended": False,
                }
            )
    return pd.DataFrame(rows)


def test_event_study_three_manual_return_cases() -> None:
    signals = pd.DataFrame(
        {
            "symbol": ["sh600000", "sz000001", "sh601318"],
            "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
            "sig": [True, True, True],
        }
    )

    result = run_event_study(signals, horizons=[1, 3], prices=_prices())
    events = result.events.sort_values(["symbol", "horizon"]).reset_index(drop=True)

    first = events[(events["symbol"].eq("sh600000")) & (events["horizon"].eq(1))].iloc[0]
    third = events[(events["symbol"].eq("sh600000")) & (events["horizon"].eq(3))].iloc[0]
    second_symbol = events[(events["symbol"].eq("sz000001")) & (events["horizon"].eq(1))].iloc[0]

    # v1 口径：ret_h = close(entry+h) / open(entry) − 1（入场日之后再持有 h 天）
    assert first["entry_date"] == pd.Timestamp("2020-01-02")
    assert first["exit_date"] == pd.Timestamp("2020-01-03")
    assert first["return"] == (103.0 / 101.0) - 1.0
    assert third["exit_date"] == pd.Timestamp("2020-01-05")
    assert third["return"] == (105.0 / 101.0) - 1.0
    assert second_symbol["return"] == (204.0 / 202.0) - 1.0
    assert result.pooled.set_index("horizon").loc[1, "count"] == 3
    assert result.pooled.set_index("horizon").loc[3, "count"] == 3
    # signals 统计 = 有效入场数（v1 signal_count 语义）
    assert result.per_symbol["signals"].tolist() == [1, 1, 1, 1, 1, 1]


def test_entry_filters_and_exit_missing_counts() -> None:
    prices = _prices()
    prices.loc[
        (prices["symbol"].eq("sh600000")) & (prices["date"].eq("2020-01-02")), "is_suspended"
    ] = True
    prices.loc[
        (prices["symbol"].eq("sz000001")) & (prices["date"].eq("2020-01-03")), "limit_up_price"
    ] = 202.0
    signals = pd.DataFrame(
        {
            "symbol": ["sh600000", "sz000001", "sh601318", "sh601318"],
            "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-06", "2020-01-08"]),
            "sig": [True, True, True, True],
        }
    )

    result = run_event_study(signals, horizons=[1, 3], prices=prices)

    assert result.exclusions["entry_suspended"] == 1
    assert result.exclusions["entry_limit_up"] == 1
    assert result.exclusions["entry_missing"] == 1
    assert result.exclusions["exit_missing"] == 1
    assert result.events["symbol"].tolist() == ["sh601318"]
    assert result.events["horizon"].tolist() == [1]

    # parity 模式：entry_filters="none" 复刻 v1（不剔除停牌/一字板）
    unfiltered = run_event_study(signals, horizons=[1, 3], prices=prices, entry_filters="none")
    assert unfiltered.exclusions["entry_suspended"] == 0
    assert unfiltered.exclusions["entry_limit_up"] == 0
    assert set(unfiltered.events["symbol"]) == {"sh600000", "sz000001", "sh601318"}


def test_by_year_split_uses_entry_year() -> None:
    prices = pd.DataFrame(
        {
            "symbol": ["sh600000"] * 4,
            "date": pd.to_datetime(["2020-12-30", "2020-12-31", "2021-01-01", "2021-01-02"]),
            "open": [10.0, 11.0, 12.0, 13.0],
            "close": [10.5, 11.5, 12.5, 13.5],
            "raw_open": [10.0, 11.0, 12.0, 13.0],
            "limit_up_price": [np.nan] * 4,
            "is_suspended": [False] * 4,
        }
    )
    signals = pd.DataFrame(
        {
            "symbol": ["sh600000", "sh600000"],
            "date": pd.to_datetime(["2020-12-30", "2020-12-31"]),
            "sig": [True, True],
        }
    )

    result = run_event_study(signals, horizons=[1], prices=prices)
    got = result.by_year.set_index("year")["count"].to_dict()

    assert got == {2020: 1, 2021: 1}


def test_multiindex_signals_and_report_render() -> None:
    signals = pd.DataFrame(
        {"sig": [True]},
        index=pd.MultiIndex.from_tuples(
            [("sh600000", pd.Timestamp("2020-01-01"))], names=["symbol", "date"]
        ),
    )

    result = run_event_study(signals, horizons=[1], prices=_prices())

    assert result.per_symbol.iloc[0]["symbol"] == "sh600000"
    assert "Pooled" in result.to_report()
