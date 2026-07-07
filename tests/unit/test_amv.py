from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.etl.staging import parse_day_bytes
from quant.indicators.amv import amv, amv_timing_signal
from quant.signals import registry
from quant.tdx import functions as F

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture_ohlcv(symbol: str = "sh999999") -> pd.DataFrame:
    buf = (FIXTURES / "tdx" / "lday" / f"{symbol}.day").read_bytes()
    return parse_day_bytes(buf, symbol).reset_index(drop=True)


def _manual_amv_close(df: pd.DataFrame, *, n: int = 10, k: float = 2.13) -> pd.Series:
    amount_smooth = F.SMA(df["amount"], n, 1) / 1_000_000.0
    prev_close_ma5 = F.MA(F.REF(df["close"], 1), 5)
    return amount_smooth * df["close"] / prev_close_ma5 * 0.1 * k


def test_amv_formula_matches_tdx_composition() -> None:
    df = _fixture_ohlcv()
    got = amv(df)
    amount_smooth = F.SMA(df["amount"], 10, 1) / 1_000_000.0
    prev_close_ma5 = F.MA(F.REF(df["close"], 1), 5)
    scale = amount_smooth / prev_close_ma5 * 0.1 * 2.13
    expected_close = scale * df["close"]
    expected_prev = F.REF(expected_close, 1)
    expected_pct = ((expected_close - expected_prev) / expected_prev * 100.0).where(
        expected_prev != 0
    )

    np.testing.assert_allclose(got["amv_open"], scale * df["open"], rtol=1e-12, equal_nan=True)
    np.testing.assert_allclose(got["amv_high"], scale * df["high"], rtol=1e-12, equal_nan=True)
    np.testing.assert_allclose(got["amv_low"], scale * df["low"], rtol=1e-12, equal_nan=True)
    np.testing.assert_allclose(got["amv_close"], expected_close, rtol=1e-12, equal_nan=True)
    np.testing.assert_allclose(got["amv_pct"], expected_pct, rtol=1e-12, equal_nan=True)
    np.testing.assert_allclose(got["amv_life"], F.EMA(expected_close, 12), rtol=1e-12)


def test_amv_k_parameter_changes_scale() -> None:
    df = _fixture_ohlcv()
    got = amv(df, k=2.07)
    expected = _manual_amv_close(df, k=2.07)

    np.testing.assert_allclose(got["amv_close"], expected, rtol=1e-12, equal_nan=True)


def test_amv_timing_state_machine() -> None:
    frame = pd.DataFrame(
        {"amv_pct": [5.0, -1.0, -2.4, 3.0, 2.0, 1.0, 4.5, -3.0, 2.5, 1.6, -2.2, 0.0]}
    )

    got = amv_timing_signal(frame)

    assert got["sig_amv_buy"].tolist() == [
        True,
        True,
        False,
        False,
        True,
        False,
        True,
        False,
        False,
        True,
        False,
        False,
    ]
    assert got["sig_amv_sell"].tolist() == [
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
    ]
    assert got["regime"].tolist() == [1, 1, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1]


def test_amv_timing_sell_wins_same_bar() -> None:
    got = amv_timing_signal(pd.DataFrame({"amv_pct": [5.0]}), buy_th=4.0, sell_th=5.0)

    assert got["sig_amv_buy"].iloc[0]
    assert got["sig_amv_sell"].iloc[0]
    assert got["regime"].iloc[0] == 0


def test_amv_handles_zero_and_nan_amount() -> None:
    df = _fixture_ohlcv().iloc[:40].copy()
    df.loc[df.index[10], "amount"] = 0.0
    df.loc[df.index[11], "amount"] = np.nan

    got = amv(df)

    assert len(got) == len(df)
    assert not np.isinf(got.select_dtypes(float).to_numpy()).any()


def test_amv_regime_registry_and_duplicate_guard() -> None:
    df = _fixture_ohlcv()
    signal = registry.get("amv_regime")
    got = signal(df)
    want = amv_timing_signal(amv(df))["regime"]

    pd.testing.assert_series_equal(got, want, check_names=False)
    assert "amv_regime" in registry.names()

    with pytest.raises(ValueError, match="already registered"):

        @registry.register("amv_regime")
        def duplicate(_df: pd.DataFrame) -> pd.Series:
            return pd.Series(0, index=_df.index)
