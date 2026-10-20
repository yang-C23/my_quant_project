from __future__ import annotations

import numpy as np
import pandas as pd

from quant.etl.basics import compute_basics


def test_compute_basics_preclose_returns_and_share_timeline() -> None:
    daily = pd.DataFrame(
        {
            "symbol": ["sh600000"] * 4,
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
            "open": [10.0, 10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5, 13.5],
            "low": [9.5, 9.8, 10.8, 11.8],
            "close": [10.0, 11.0, 12.0, 13.0],
            "volume": [100_000, 200_000, 300_000, 450_000],
            "amount": [1_000_000.0, 2_100_000.0, 3_400_000.0, 5_600_000.0],
        }
    )
    gbbq = pd.DataFrame(
        [
            ("sh600000", "2024-01-01", 5, 0.0, 0.0, 100.0, 200.0),
            ("sh600000", "2024-01-02", 1, 1.0, 0.0, 0.0, 0.0),
            ("sh600000", "2024-01-03", 5, 0.0, 0.0, 150.0, 250.0),
        ],
        columns=["symbol", "date", "category", "c1", "c2", "c3", "c4"],
    )
    gbbq["date"] = pd.to_datetime(gbbq["date"])

    got = compute_basics(daily, gbbq)

    np.testing.assert_allclose(got["preclose"], [10.0, 9.9, 11.0, 12.0], rtol=1e-12)
    assert got["pct_chg"].tolist() == [0.0, 11.11, 9.09, 8.33]
    assert got["amplitude"].tolist() == [10.0, 17.17, 15.45, 14.17]
    np.testing.assert_allclose(got["float_shares"], [1_000_000, 1_000_000, 1_500_000, 1_500_000])
    np.testing.assert_allclose(got["total_shares"], [2_000_000, 2_000_000, 2_500_000, 2_500_000])
    np.testing.assert_allclose(got["turnover"], [0.1, 0.2, 0.2, 0.3])
    np.testing.assert_allclose(
        got["float_mktcap"], [10_000_000, 11_000_000, 18_000_000, 19_500_000]
    )
    np.testing.assert_allclose(
        got["total_mktcap"], [20_000_000, 22_000_000, 30_000_000, 32_500_000]
    )


def test_compute_basics_handles_missing_shares_and_zero_preclose() -> None:
    daily = pd.DataFrame(
        {
            "symbol": ["sh600000", "sh600000"],
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "open": [0.0, 0.0],
            "high": [0.0, 0.0],
            "low": [0.0, 0.0],
            "close": [0.0, 0.0],
            "volume": [100, 200],
            "amount": [0.0, 0.0],
        }
    )

    got = compute_basics(daily, pd.DataFrame())

    assert got["pct_chg"].isna().all()
    assert got["amplitude"].isna().all()
    assert got["turnover"].isna().all()
    assert got["float_mktcap"].isna().all()
    assert got["total_mktcap"].isna().all()
