"""Derivative features must keep expiry, future observations and missing evidence separate."""

import numpy as np
import pandas as pd
import pytest

from quant.longterm.derivative_features import (
    factor_confirmation,
    futures_basis_features,
    nominal_expiry,
    options_activity_features,
    seasonal_rank,
)


def test_constant_maturity_does_not_extrapolate_or_change_with_future_prices():
    dates = pd.bdate_range("2020-01-02", "2020-04-01")
    calendar = pd.bdate_range("2020-01-01", "2020-12-31")
    source = pd.DataFrame(
        [
            {"symbol": symbol, "date": date, "close": price, "volume": 100}
            for date in dates
            for symbol, price in [("IF2001", 99.0), ("IF2002", 98.0)]
        ]
    )
    spot = pd.Series(100.0, index=dates)
    config = {
        "first_aligned_close": "2016-01-01",
        "target_calendar_days": 30,
        "historical_window_years": 3,
        "seasonal_window_calendar_days": 45,
        "minimum_prior_observations": 40,
    }
    full, _ = futures_basis_features(source, spot, "IF", config, expiry_calendar=calendar)
    prefix, _ = futures_basis_features(
        source[source.date <= dates[12]],
        spot.iloc[:13],
        "IF",
        config,
        expiry_calendar=calendar,
    )
    pd.testing.assert_frame_equal(prefix, full.iloc[:13])
    assert full.basis_30d.dropna().between(-0.02 - 1e-12, -0.01 + 1e-12).all()
    assert full.loc["2020-02-25":, "basis_30d"].isna().all()
    assert nominal_expiry("IO2002-P-3000") == pd.Timestamp("2020-02-21")


def test_seasonal_rank_requires_past_years_and_never_uses_future_values():
    dates = pd.bdate_range("2016-01-01", "2021-01-01")
    values = pd.Series(np.linspace(-0.02, 0.02, len(dates)), index=dates)
    out = seasonal_rank(values, years=3, radius=45, minimum=40)
    assert out.loc[:"2018-12-31"].isna().all()
    assert out.dropna().eq(1).all()
    pd.testing.assert_series_equal(
        out.iloc[:900], seasonal_rank(values.iloc[:900], years=3, radius=45, minimum=40)
    )


def test_factor_cannot_confirm_before_extreme_or_with_missing_evidence():
    dates = pd.bdate_range("2020-01-01", periods=5)
    stages = pd.DataFrame(
        {
            "event_id": 1,
            "sessions_since_event_low": 5,
            "close": 10,
            "sma_10": 9,
        },
        index=dates,
    )
    extreme = pd.Series([False, True, False, False, False], index=dates)
    relieved = pd.Series([True, False, True, True, True], index=dates)
    available = pd.Series([True, True, False, True, True], index=dates)
    signals = factor_confirmation(stages, extreme, relieved, available)
    assert signals.tolist() == [False, False, False, True, False]
    assert signals.sum() == pytest.approx(1)


def test_option_unit_failure_cannot_create_an_artificial_deep_put_share():
    dates = pd.bdate_range("2020-01-02", periods=3)
    contracts = pd.DataFrame(
        [
            {
                "symbol": symbol,
                "date": date,
                "volume": 100,
                "low": 9,
                "high": 11,
                "turnover_source_value": turnover,
                "delta": delta,
            }
            for date in dates
            for symbol, turnover, delta in [
                ("IO2001-P-3000", 10, -0.1),
                ("IO2001-C-3000", 1000, 0.1),
            ]
        ]
    )
    frame, audit = options_activity_features(
        contracts,
        pd.Series(3000, index=dates),
        "IO",
        {"maturity_days": [7, 45], "delta_abs_range": [0.05, 0.15], "history_years": 2},
        expiry_calendar=pd.bdate_range("2020-01-01", "2020-12-31"),
    )
    assert audit["turnover_price_unit_failures"] == 3
    assert frame.deep_put_premium_share.isna().all()
    assert frame.valid_trade_turnover_coverage.max() < 0.05
