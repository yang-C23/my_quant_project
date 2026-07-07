from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.etl.adjust import compute_adjust, theoretical_preclose

FIXTURES = Path(__file__).parent.parent / "fixtures" / "adjust"


def _event(symbol: str, date: str, c1: float, c2: float, c3: float, c4: float) -> dict:
    return {
        "symbol": symbol,
        "date": pd.Timestamp(date),
        "category": 1,
        "c1": c1,
        "c2": c2,
        "c3": c3,
        "c4": c4,
    }


@pytest.mark.parametrize(
    ("symbol", "event", "expected_ratio"),
    [
        ("sh600001", _event("sh600001", "2024-01-02", 1.0, 0.0, 0.0, 0.0), 10.0 / 9.9),
        ("sh600002", _event("sh600002", "2024-01-02", 0.0, 0.0, 10.0, 0.0), 2.0),
        ("sh600003", _event("sh600003", "2024-01-02", 0.0, 5.0, 0.0, 4.0), 1.25),
        (
            "sh600004",
            _event("sh600004", "2024-01-02", 2.0, 0.0, 5.0, 0.0),
            10.0 / round(98.0 / 15.0, 4),
        ),
    ],
)
def test_compute_adjust_manual_xdxr_cases(symbol: str, event: dict, expected_ratio: float) -> None:
    daily = pd.DataFrame(
        {
            "symbol": [symbol, symbol, symbol],
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "close": [10.0, 11.0, 12.0],
        }
    )
    got = compute_adjust(daily, pd.DataFrame([event]))

    assert got["hfq_factor"].iloc[0] == 1.0
    assert got["hfq_factor"].iloc[1] == pytest.approx(round(expected_ratio, 8), rel=1e-12)
    assert got["hfq_factor"].iloc[2] == pytest.approx(round(expected_ratio, 8), rel=1e-12)


def test_theoretical_preclose_formula() -> None:
    prev_close = pd.Series([10.0, 10.0, 10.0, 10.0])
    events = pd.DataFrame(
        {
            "fenhong": [1.0, 0.0, 0.0, 2.0],
            "peigu": [0.0, 0.0, 5.0, 0.0],
            "songzhuangu": [0.0, 10.0, 0.0, 5.0],
            "peigujia": [0.0, 0.0, 4.0, 0.0],
        }
    )

    np.testing.assert_allclose(
        theoretical_preclose(prev_close, events),
        [9.9, 5.0, 8.0, 98.0 / 15.0],
        rtol=1e-12,
    )


def test_compute_adjust_no_xdxr_hfq_one_and_qfq_latest_one() -> None:
    daily = pd.DataFrame(
        {
            "symbol": ["sh600000"] * 4,
            "date": pd.date_range("2024-01-01", periods=4),
            "close": [10.0, 10.5, 10.2, 10.8],
        }
    )

    got = compute_adjust(
        daily, pd.DataFrame(columns=["symbol", "date", "category", "c1", "c2", "c3", "c4"])
    )

    np.testing.assert_allclose(got["hfq_factor"], 1.0)
    assert got["qfq_factor"].iloc[-1] == 1.0


def test_compute_adjust_matches_pg_sz000001_fixture() -> None:
    daily_close = pd.read_csv(FIXTURES / "pg_sz000001_daily_close.csv", parse_dates=["date"])
    daily = daily_close.assign(symbol="sz000001")
    gbbq = pd.read_csv(FIXTURES / "pg_sz000001_gbbq_xdxr.csv", parse_dates=["date"])
    gbbq = gbbq.assign(symbol="sz000001", category=1)
    expected = pd.read_csv(FIXTURES / "pg_sz000001_adjust.csv", parse_dates=["date"])

    got = compute_adjust(daily, gbbq)
    got["date"] = pd.to_datetime(got["date"])
    merged = expected.merge(got, on="date", how="inner", suffixes=("_pg", "_got"))

    assert len(merged) == len(expected)
    np.testing.assert_allclose(
        merged["hfq_factor_got"], merged["hfq_factor_pg"], rtol=1e-9, atol=1e-12
    )
