"""Tie, boundary, calendar and future-invariance tests for the optimized rank."""

import numpy as np
import pandas as pd
import pytest

from quant.longterm.features import historical_percentile


@pytest.mark.parametrize("expanding", [False, True])
@pytest.mark.parametrize("positive_only", [False, True])
def test_midrank_exact_calendar_oracle(expanding, positive_only):
    dates = pd.bdate_range("2016-02-29", "2021-03-03")
    values = np.resize([1.0, 2.0, 2.0, 4.0, 0.0, -2.0, np.nan, np.inf], len(dates))
    series = pd.Series(values, index=dates)
    actual = historical_percentile(
        series, years=1, expanding=expanding, positive_only=positive_only, minimum_coverage=0.5
    )
    valid = np.isfinite(values) & ((values > 0) if positive_only else True)
    first = dates[np.flatnonzero(valid)[0]]
    for i in sorted(set(range(0, len(series), 31)) | {260, 261, 262, len(series) - 1}):
        selected = [
            values[j]
            for j in range(i)
            if valid[j] and (expanding or dates[j] >= dates[i] - pd.DateOffset(years=1))
        ]
        if not valid[i] or dates[i] < first + pd.DateOffset(years=1) or len(selected) < 126:
            assert pd.isna(actual.iloc[i])
        else:
            expected = (
                sum(x < values[i] for x in selected) + 0.5 * sum(x == values[i] for x in selected)
            ) / len(selected)
            assert actual.iloc[i] == expected
    prefix = historical_percentile(
        series.iloc[:1000],
        years=1,
        expanding=expanding,
        positive_only=positive_only,
        minimum_coverage=0.5,
    )
    pd.testing.assert_series_equal(prefix, actual.iloc[:1000], check_exact=True)


def test_all_ties_are_half_and_future_extreme_does_not_change_past():
    series = pd.Series(3.0, index=pd.bdate_range("2020-01-01", periods=600))
    actual = historical_percentile(series, years=1)
    assert set(actual.dropna()) == {0.5}
    series.iloc[-1] = 1e100
    pd.testing.assert_series_equal(
        actual.iloc[:-1], historical_percentile(series, years=1).iloc[:-1], check_exact=True
    )
