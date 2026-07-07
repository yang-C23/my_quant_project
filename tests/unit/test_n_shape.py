from __future__ import annotations

import pandas as pd

from quant.indicators.n_shape import n_shape


def _frame(lows: list[float], highs: list[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=len(lows), freq="D")
    highs = highs or lows
    close = [(lo + hi) / 2.0 for lo, hi in zip(lows, highs, strict=True)]
    return pd.DataFrame({"low": lows, "high": highs, "close": close}, index=dates)


def test_n_shape_detects_low_rebound_pullback() -> None:
    df = _frame(
        lows=[10.0, 9.0, 9.4, 9.6, 9.2, 9.3],
        highs=[10.2, 9.2, 10.0, 10.1, 9.7, 9.8],
    )

    got = n_shape(df, lookback=6, rebound_pct=0.08)

    assert got.tolist() == [False, False, False, True, True, True]


def test_n_shape_rejects_pullback_breaking_first_low() -> None:
    df = _frame(
        lows=[10.0, 9.0, 9.4, 9.6, 8.9, 9.3],
        highs=[10.2, 9.2, 10.0, 10.1, 9.7, 9.8],
    )

    got = n_shape(df, lookback=6, rebound_pct=0.08)

    assert not bool(got.iloc[-1])


def test_n_shape_does_not_read_future_bars() -> None:
    df = _frame(
        lows=[10.0, 9.0, 9.4, 9.6, 9.2, 9.3, 1.0],
        highs=[10.2, 9.2, 10.0, 10.1, 9.7, 9.8, 50.0],
    )
    base = n_shape(df.iloc[:6], lookback=6, rebound_pct=0.08)
    with_future = n_shape(df, lookback=6, rebound_pct=0.08)

    pd.testing.assert_series_equal(base, with_future.iloc[:6], check_names=False)
