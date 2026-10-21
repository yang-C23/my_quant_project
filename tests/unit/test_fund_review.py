"""Published NAV growth and spendable-cash returns use different dividend timing."""

import pandas as pd
import pytest

from quant.longterm.fund_review import disclosure_nav_index


def test_published_growth_is_not_ex_date_reinvestment_return():
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    nav = pd.Series([10.0, 7.5, 8.0], index=dates)
    actions = pd.DataFrame(
        [
            {
                "kind": "dividend",
                "ex_date": dates[1],
                "per_share": 2.0,
            }
        ]
    )
    result = disclosure_nav_index(nav, actions)
    assert result.iloc[1] == pytest.approx(7.5 / (10 - 2))
    assert result.iloc[1] != pytest.approx((7.5 + 2) / 10)
    assert result.iloc[-1] == pytest.approx(1)


def test_disclosure_split_does_not_lose_value_or_use_future_nav():
    dates = pd.bdate_range("2020-01-02", periods=3)
    nav = pd.Series([10.0, 5.0, 6.0], index=dates)
    actions = pd.DataFrame([{"kind": "split", "ex_date": dates[1], "ratio": 2.0}])
    full = disclosure_nav_index(nav, actions)
    assert full.iloc[1] == pytest.approx(1)
    pd.testing.assert_series_equal(full.iloc[:2], disclosure_nav_index(nav.iloc[:2], actions))
