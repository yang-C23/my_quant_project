"""Dependent event clusters and non-entry cash must not disappear from comparisons."""

import pandas as pd
import pytest

from quant.longterm.pool_analysis import clustered_event_comparisons, crisis_labels


def test_crisis_clusters_not_daily_signal_count_and_nonentry_cash_retained():
    rows = []
    for event, date in enumerate(["2008-01-01", "2008-01-25", "2020-03-01", "2022-05-01"]):
        rows += [
            {
                "asset": "X",
                "stage": "pressure",
                "event_id": event,
                "event_date": date,
                "status": "entered",
                "event_horizon_return_252": 0.20,
            },
            {
                "asset": "X",
                "stage": "stabilized",
                "event_id": event,
                "event_date": date,
                "status": "no_confirmation_in_window",
                "event_horizon_return_252": 0.0,
            },
            {
                "asset": "X",
                "stage": "vix_relief",
                "event_id": event,
                "event_date": date,
                "status": "factor_unavailable",
                "event_horizon_return_252": None,
            },
        ]
    config = {
        "crisis_gap_days": 120,
        "bootstrap_seed": 7,
        "horizons": [252],
        "bootstrap_repetitions": 100,
    }
    results, leave_out = clustered_event_comparisons(pd.DataFrame(rows), config)
    row = results[results.stage.eq("stabilized")].iloc[0]
    assert row.paired_events == 4 and row.crisis_clusters == 3
    assert row.equal_crisis_mean_delta == pytest.approx(-0.2)
    assert row.ci_high == pytest.approx(-0.2)
    assert len(leave_out) == 3
    missing = results[results.stage.eq("vix_relief")].iloc[0]
    assert missing.paired_events == 0 and pd.isna(missing.equal_crisis_mean_delta)
    pd.testing.assert_frame_equal(
        results, clustered_event_comparisons(pd.DataFrame(rows), config)[0]
    )


def test_crisis_assignment_is_unchanged_when_later_dates_arrive():
    dates = pd.Series(["2008-01-01", "2008-01-20", "2020-03-01"])
    extended = pd.concat([dates, pd.Series(["2020-03-20", "2022-02-01"])], ignore_index=True)
    pd.testing.assert_series_equal(crisis_labels(dates, 120), crisis_labels(extended, 120).iloc[:3])
