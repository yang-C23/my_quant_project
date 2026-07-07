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
SENT = 99_999_999.0


def _fixture_ohlcv(symbol: str) -> pd.DataFrame:
    buf = (FIXTURES / "tdx" / "lday" / f"{symbol}.day").read_bytes()
    return parse_day_bytes(buf, symbol).reset_index(drop=True)


def _golden(symbol: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "goldens" / f"bt_legacy_{symbol}.csv")


def _naive_tdx_volume_breath(volume: pd.Series, n: int) -> pd.DataFrame:
    values = volume.astype(float).tolist()
    vh1: list[float] = []
    vh2: list[float] = []
    vh3: list[float] = []
    vl1: list[float] = []
    vl2: list[float] = []
    vl3: list[float] = []
    h2_line: list[float] = []
    h3_line: list[float] = []
    l2_line: list[float] = []
    l3_line: list[float] = []
    for i, value in enumerate(values):
        v_window = values[i - n + 1 : i + 1]
        full_valid = len(v_window) == n and not any(pd.isna(v) for v in v_window)
        vh1.append(max(v_window) if full_valid else np.nan)
        vl1.append(min(v_window) if full_valid else np.nan)
        h2_line.append(value if pd.notna(vh1[-1]) and value < vh1[-1] else 0.0)
        l2_line.append(value if pd.notna(vl1[-1]) and value > vl1[-1] else SENT)
        vh2.append(max(h2_line[i - n + 1 : i + 1]) if i >= n - 1 else np.nan)
        vl2.append(min(l2_line[i - n + 1 : i + 1]) if i >= n - 1 else np.nan)
        h3_line.append(value if pd.notna(vh2[-1]) and value < vh2[-1] else 0.0)
        l3_line.append(value if pd.notna(vl2[-1]) and value > vl2[-1] else SENT)
        vh3.append(max(h3_line[i - n + 1 : i + 1]) if i >= n - 1 else np.nan)
        vl3.append(min(l3_line[i - n + 1 : i + 1]) if i >= n - 1 else np.nan)

    return pd.DataFrame(
        {
            "avghigh": (pd.Series(vh1) + pd.Series(vh2) + pd.Series(vh3)) / 3.0,
            "avglow": (pd.Series(vl1) + pd.Series(vl2) + pd.Series(vl3)) / 3.0,
        },
        index=volume.index,
    )


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


def test_volume_breath_matches_naive_tdx_oracle() -> None:
    df = pd.DataFrame(
        {
            "close": [10.0, 10.2, 10.1, 10.3, 10.4, 10.5, 10.6, 10.7, 10.6, 10.8],
            "high": [10.1, 10.3, 10.2, 10.4, 10.5, 10.6, 10.7, 10.8, 10.7, 10.9],
            "low": [9.9, 10.0, 9.8, 10.1, 10.2, 10.3, 10.4, 10.5, 10.3, 10.6],
            "volume": [10, 30, 30, 20, 5, 40, 20, 35, 40, 15],
        }
    )

    got = dual_trend(df, n1=2, m=(2, 2, 2, 2), n_vol=5)
    want = _naive_tdx_volume_breath(df["volume"], 5)

    np.testing.assert_allclose(got["avghigh"], want["avghigh"], rtol=1e-10, equal_nan=True)
    np.testing.assert_allclose(got["avglow"], want["avglow"], rtol=1e-10, equal_nan=True)


@pytest.mark.parametrize("symbol", ["sh600000", "sz000001"])
def test_volume_breath_vs_sorted_golden_diff_snapshot(symbol: str) -> None:
    df = _fixture_ohlcv(symbol)
    got = dual_trend(df)
    golden = _golden(symbol)
    valid_breath = ~golden["avghigh"].isna()

    extrema_diff = (
        ~np.isclose(
            got["avghigh"].astype(float),
            golden["avghigh"].astype(float),
            rtol=1e-8,
            atol=1e-8,
            equal_nan=True,
        )
        | ~np.isclose(
            got["avglow"].astype(float),
            golden["avglow"].astype(float),
            rtol=1e-8,
            atol=1e-8,
            equal_nan=True,
        )
    ) & valid_breath.to_numpy()
    activity_diff = (
        got["breath_active"].astype(float).to_numpy() != golden["activity"].astype(float).to_numpy()
    ) & valid_breath.to_numpy()
    snapshot = {
        "sh600000": {"extrema": 149, "activity": 13, "comparable": 171},
        "sz000001": {"extrema": 171, "activity": 40, "comparable": 171},
    }[symbol]

    print(
        f"{symbol}: extrema_diff={int(extrema_diff.sum())}/{int(valid_breath.sum())}, "
        f"activity_diff={int(activity_diff.sum())}"
    )
    assert int(extrema_diff.sum()) == snapshot["extrema"]
    assert int(activity_diff.sum()) == snapshot["activity"]
    assert int(valid_breath.sum()) == snapshot["comparable"]


def test_dual_trend_entry_registry_and_duplicate_guard() -> None:
    df = _fixture_ohlcv("sz000001")
    signal = registry.get("dual_trend_entry")
    got = signal(df)
    want = dual_trend(df)["sig_dual_trend_entry"]

    pd.testing.assert_series_equal(got, want, check_names=False)
    assert {"amv_regime", "kdj_oversold", "dual_trend_entry"}.issubset(registry.names())
    assert "dual_trend_entry" in registry.names()

    with pytest.raises(ValueError, match="already registered"):

        @registry.register("dual_trend_entry")
        def duplicate(_df: pd.DataFrame) -> pd.Series:
            return pd.Series(False, index=_df.index)
