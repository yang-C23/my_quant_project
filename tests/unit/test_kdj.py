from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.etl.staging import parse_day_bytes
from quant.indicators.kdj import kdj
from quant.signals.registry import get

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture_ohlcv(symbol: str) -> pd.DataFrame:
    buf = (FIXTURES / "tdx" / "lday" / f"{symbol}.day").read_bytes()
    return parse_day_bytes(buf, symbol).reset_index(drop=True)


def _golden(symbol: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "goldens" / f"bt_legacy_{symbol}.csv")


@pytest.mark.parametrize("symbol", ["sh600000", "sz000001"])
def test_kdj_matches_bt_golden(symbol: str) -> None:
    got = kdj(_fixture_ohlcv(symbol))
    golden = _golden(symbol)

    np.testing.assert_allclose(got["k"], golden["k"], rtol=1e-8, equal_nan=True)
    np.testing.assert_allclose(got["d"], golden["d"], rtol=1e-8, equal_nan=True)
    np.testing.assert_allclose(got["j"], golden["j"], rtol=1e-8, atol=1e-8, equal_nan=True)


def test_kdj_zero_denominator_keeps_rsv_nan() -> None:
    df = pd.DataFrame(
        {
            "high": [10.0] * 12,
            "low": [10.0] * 12,
            "close": [10.0] * 12,
        }
    )

    assert kdj(df).isna().all().all()


def test_kdj_oversold_signal_registry() -> None:
    signal = get("kdj_oversold")
    got = signal(_fixture_ohlcv("sh600000"))
    want = (kdj(_fixture_ohlcv("sh600000"))["j"] < 13.0).fillna(False)

    assert got.dtype == bool
    pd.testing.assert_series_equal(got, want, check_names=False)
