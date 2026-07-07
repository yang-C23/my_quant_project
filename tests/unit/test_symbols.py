from __future__ import annotations

import pytest

from quant.data.symbols import board_of, exchange_of, from_qlib, to_qlib


def test_symbol_qlib_roundtrip_cn_and_us() -> None:
    assert to_qlib("sh600000") == "SH600000"
    assert from_qlib("SH600000") == "sh600000"
    assert to_qlib("us:AAPL") == "AAPL"
    assert from_qlib("AAPL") == "us:AAPL"

    with pytest.raises(ValueError, match="invalid internal symbol"):
        to_qlib("600000")


def test_exchange_of() -> None:
    assert exchange_of("sh600000") == "sh"
    assert exchange_of("sz000001") == "sz"
    assert exchange_of("bj830799") == "bj"
    assert exchange_of("us:AAPL") == "us"


@pytest.mark.parametrize(
    ("symbol", "board"),
    [
        ("sh600000", "main"),
        ("sh601000", "main"),
        ("sh603000", "main"),
        ("sh605000", "main"),
        ("sz000001", "main"),
        ("sz001001", "main"),
        ("sz002001", "main"),
        ("sz003001", "main"),
        ("sz300001", "gem"),
        ("sz301001", "gem"),
        ("sh688001", "star"),
        ("sh689001", "star"),
        ("bj830799", "bse"),
        ("sz430001", "bse"),
        ("bj899050", "index"),
        ("sh999999", "index"),
        ("sz399001", "index"),
        ("sh113001", "bond"),
        ("sz123001", "bond"),
        ("sh510050", "etf"),
        ("sz159915", "etf"),
        ("sh900901", "b"),
        ("sz200001", "b"),
    ],
)
def test_board_of_prefix_table(symbol: str, board: str) -> None:
    assert board_of(symbol) == board
