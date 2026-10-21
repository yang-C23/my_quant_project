"""Calendar completeness for the retrospective monthly ETF audit."""

from pathlib import Path
import runpy

import pandas as pd
import pytest


monthly_windows = runpy.run_path(
    str(Path(__file__).parents[2] / "scripts/research_etf_monthly_windows.py")
)["monthly_windows"]


def test_monthly_windows_keep_every_month_and_latest_partial_month():
    calendar = pd.bdate_range("2020-01-02", "2026-06-15")
    windows = monthly_windows(calendar, [5, 10])
    assert len(windows) == 18
    assert all(window["id"].startswith("rolling_5y_") for window in windows)
    assert windows[-1]["end"] == "2026-06-15"
    assert len({window["id"] for window in windows}) == len(windows)
    for window in windows:
        start, end = pd.Timestamp(window["start"]), pd.Timestamp(window["end"])
        assert end - start >= pd.Timedelta(days=5 * 365 - 7)


def test_monthly_windows_never_invent_long_history():
    assert monthly_windows(pd.bdate_range("2023-01-01", "2026-01-01"), [5, 10]) == []


def test_missing_start_prices_cannot_shorten_a_five_year_account():
    calendar = pd.bdate_range("2020-01-02", "2026-06-15")
    calendar = calendar[~calendar.to_series().between("2020-02-01", "2020-05-01")]
    with pytest.raises(ValueError, match="cannot shorten"):
        monthly_windows(calendar, [5])
