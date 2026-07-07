from __future__ import annotations

import pytest

from quant.data.api import get_ohlcv
from quant.data.universe import list_symbols


@pytest.mark.integration
def test_get_ohlcv_real_tail() -> None:
    df = get_ohlcv("sz000001", start="2024-01-01")

    assert not df.empty
    assert {"open", "high", "low", "close", "volume", "amount", "factor"}.issubset(df.columns)


@pytest.mark.integration
def test_list_symbols_real_nostar_bse() -> None:
    symbols = list_symbols(exclude_boards={"star", "bse"})

    assert symbols
    assert all(not symbol.startswith("bj") for symbol in symbols)
