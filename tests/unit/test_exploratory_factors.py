from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.research.exploratory import _top_quantile_event
from quant.signals.factors import (
    factor_bottom_area_score,
    factor_chip_concentration,
    factor_names,
    factor_red_green_vol_ratio,
    factor_turnover_weighted_cost,
    factor_washout_area_ratio,
)


def _frame() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=8, freq="D")
    return pd.DataFrame(
        {
            "open": [10, 11, 10, 9, 9, 10, 11, 10],
            "high": [11, 12, 11, 10, 10, 11, 12, 11],
            "low": [9, 10, 9, 8, 8, 9, 10, 9],
            "close": [11, 10, 9, 10, 11, 10, 12, 9],
            "volume": [10, 20, 30, 40, 50, 60, 70, 80],
            "amount": [110, 200, 270, 400, 550, 600, 840, 720],
            "turnover": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
        },
        index=dates,
    ).astype(float)


def test_red_green_vol_ratio_handcalc() -> None:
    got = factor_red_green_vol_ratio(_frame(), {"window": 3})

    assert got.iloc[2] == pytest.approx(10 / 50)
    assert got.iloc[4] == pytest.approx(90 / 30)


def test_turnover_weighted_cost_handcalc() -> None:
    got = factor_turnover_weighted_cost(_frame(), {"window": 3})
    close = _frame()["close"]
    turnover = _frame()["turnover"]
    cost = (close.iloc[:3] * turnover.iloc[:3]).sum() / turnover.iloc[:3].sum()

    assert got.iloc[2] == pytest.approx(close.iloc[2] / cost - 1.0)


def test_chip_concentration_is_weighted_dispersion() -> None:
    got = factor_chip_concentration(_frame(), {"window": 3})

    assert got.iloc[2] > 0
    assert np.isfinite(got.iloc[2])


def test_washout_and_bottom_area_are_registered() -> None:
    frame = _frame()

    assert "washout_area_ratio" in factor_names()
    assert len(factor_washout_area_ratio(frame, {"window": 3})) == len(frame)
    assert len(factor_bottom_area_score(frame, {"window": 3, "price_window": 3})) == len(frame)


def test_factors_do_not_read_future_rows() -> None:
    frame = _frame()
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] = 999.0
    funcs = [
        (factor_red_green_vol_ratio, {"window": 3}),
        (factor_turnover_weighted_cost, {"window": 3}),
        (factor_chip_concentration, {"window": 3}),
        (factor_bottom_area_score, {"window": 3, "price_window": 3}),
    ]
    for func, params in funcs:
        base = func(frame, params).iloc[:-1]
        got = func(changed, params).iloc[:-1]
        pd.testing.assert_series_equal(base, got)


def test_top_quantile_event_uses_ashare_entry_filters() -> None:
    symbols = ["sh600000", "sz000001", "sh601318", "sz000002", "sh600519"]
    factor_frame = pd.DataFrame(
        {
            "symbol": symbols,
            "date": [pd.Timestamp("2020-01-01")] * len(symbols),
            "factor": [5.0, 5.0, 5.0, 5.0, 1.0],
        }
    )
    rows = []
    returns = {
        "sh600000": 0.20,
        "sz000001": 1.00,
        "sh601318": 0.50,
        "sz000002": -0.10,
        "sh600519": 0.00,
    }
    for symbol in symbols:
        rows.extend(
            [
                {
                    "symbol": symbol,
                    "date": pd.Timestamp("2020-01-01"),
                    "open": 10.0,
                    "close": 10.0,
                    "raw_open": 10.0,
                    "is_suspended": False,
                    "limit_up_price": np.nan,
                },
                {
                    "symbol": symbol,
                    "date": pd.Timestamp("2020-01-02"),
                    "open": 10.0,
                    "close": 10.0,
                    "raw_open": 10.0,
                    "is_suspended": symbol == "sz000001",
                    "limit_up_price": 10.0 if symbol == "sh601318" else np.nan,
                },
                {
                    "symbol": symbol,
                    "date": pd.Timestamp("2020-01-03"),
                    "open": 10.0,
                    "close": 10.0 * (1.0 + returns[symbol]),
                    "raw_open": 10.0,
                    "is_suspended": False,
                    "limit_up_price": np.nan,
                },
            ]
        )
    prices = pd.DataFrame(rows)

    got = _top_quantile_event(factor_frame, prices, horizon=1)

    assert got["avg_return"] == pytest.approx(0.05)
    assert got["profit_factor"] == pytest.approx(2.0)
