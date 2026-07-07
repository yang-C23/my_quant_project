from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.etl.staging import parse_day_bytes
from quant.indicators.dual_trend import dual_trend
from quant.signals import registry
from quant.tdx import functions as F

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture_ohlcv(symbol: str) -> pd.DataFrame:
    buf = (FIXTURES / "tdx" / "lday" / f"{symbol}.day").read_bytes()
    return parse_day_bytes(buf, symbol).reset_index(drop=True)


def _golden(symbol: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "goldens" / f"bt_legacy_{symbol}.csv")


def _duplicate_volume_window(volume: pd.Series, window: int) -> pd.Series:
    flags = np.zeros(len(volume), dtype=bool)
    values = volume.to_numpy()
    for i in range(window - 1, len(values)):
        w = values[i - window + 1 : i + 1]
        flags[i] = len(set(w)) < len(w)
    return pd.Series(flags, index=volume.index)


@pytest.mark.parametrize("symbol", ["sh600000", "sz000001"])
def test_dual_trend_white_yellow_matches_golden(symbol: str) -> None:
    df = _fixture_ohlcv(symbol)
    got = dual_trend(df)
    golden = _golden(symbol)

    np.testing.assert_allclose(
        got["yellow"], golden["long_trend"], rtol=1e-10, atol=1e-10, equal_nan=True
    )
    # bt_legacy uses classic EMA seeded by SMA; TDX EMA seeds from x0.
    # The planned parity window starts after convergence.
    np.testing.assert_allclose(
        got["white"].iloc[150:],
        golden["short_trend"].iloc[150:],
        rtol=1e-6,
        atol=1e-6,
        equal_nan=True,
    )


def test_dual_trend_white_uses_tdx_ema_seed() -> None:
    df = pd.DataFrame(
        {
            "close": [10.0, 11.0, 12.0, 13.0, 12.0, 11.0],
            "high": [10.0, 11.0, 12.0, 13.0, 12.0, 11.0],
            "low": [10.0, 11.0, 12.0, 13.0, 12.0, 11.0],
            "volume": [100, 110, 120, 130, 140, 150],
        }
    )
    got = dual_trend(df, n1=2, m=(2, 2, 2, 2), n_vol=3)
    want = F.EMA(F.EMA(df["close"], 2), 2)

    np.testing.assert_allclose(got["white"], want, rtol=1e-12)
    assert got["white"].iloc[0] == df["close"].iloc[0]


def test_volume_breath_tdx_distinct_extrema_micro_case() -> None:
    df = pd.DataFrame(
        {
            "close": [10.0, 10.2, 10.1, 10.3, 10.4, 10.5, 10.6],
            "high": [10.1, 10.3, 10.2, 10.4, 10.5, 10.6, 10.7],
            "low": [9.9, 10.0, 9.8, 10.1, 10.2, 10.3, 10.4],
            "volume": [10, 30, 30, 20, 5, 40, 20],
        }
    )

    got = dual_trend(df, n1=2, m=(2, 2, 2, 2), n_vol=7)
    sorted_high3 = sum(sorted(df["volume"])[-3:]) / 3

    assert got["avghigh"].iloc[-1] == pytest.approx((40 + 30 + 20) / 3)
    assert got["avglow"].iloc[-1] == pytest.approx((5 + 10 + 20) / 3)
    assert got["avghigh"].iloc[-1] != pytest.approx(sorted_high3)


@pytest.mark.parametrize("symbol", ["sh600000", "sz000001"])
def test_volume_breath_diffs_are_only_duplicate_windows(symbol: str) -> None:
    df = _fixture_ohlcv(symbol)
    got = dual_trend(df)
    golden = _golden(symbol)
    duplicate_window = _duplicate_volume_window(df["volume"], 30)
    valid_breath = ~golden["avghigh"].isna()

    diff_any = np.zeros(len(df), dtype=bool)
    for got_col, golden_col in [
        ("avghigh", "avghigh"),
        ("avglow", "avglow"),
        ("breath_active", "activity"),
    ]:
        left = got[got_col].astype(float)
        right = golden[golden_col].astype(float)
        diff = ~np.isclose(left, right, rtol=1e-8, atol=1e-8, equal_nan=True)
        diff &= valid_breath.to_numpy()
        diff_any |= diff

    diff_series = pd.Series(diff_any, index=df.index)
    comparable = int(valid_breath.sum())
    diff_dates = df.loc[diff_series, "date"].astype(str).tolist()
    assert int(diff_series.sum()) / comparable <= 0.05
    assert duplicate_window[diff_series].all(), diff_dates


def test_dual_trend_entry_registry_and_duplicate_guard() -> None:
    df = _fixture_ohlcv("sz000001")
    signal = registry.get("dual_trend_entry")
    got = signal(df)
    want = dual_trend(df)["sig_dual_trend_entry"]

    pd.testing.assert_series_equal(got, want, check_names=False)
    assert "dual_trend_entry" in registry.names()

    with pytest.raises(ValueError, match="already registered"):

        @registry.register("dual_trend_entry")
        def duplicate(_df: pd.DataFrame) -> pd.Series:
            return pd.Series(False, index=_df.index)
