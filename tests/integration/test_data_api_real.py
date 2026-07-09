from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.config import get_settings
from quant.data.api import get_ohlcv, get_ohlcv_batch
from quant.data.universe import list_symbols

_ALL_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
    "turnover",
    "suspended",
    "limit_up_price",
    "limit_down_price",
)


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


def _real_sample_with_delisted(n: int = 30) -> list[str]:
    universe = list_symbols(exclude_boards={"star", "b"}, at=None)
    universe_set = set(universe)
    securities = pd.read_parquet(get_settings().staging_dir / "securities.parquet")
    securities["delist_date"] = pd.to_datetime(securities["delist_date"])
    delisted = securities[
        securities["symbol"].isin(universe_set)
        & securities["sec_type"].eq("stock")
        & securities["delist_date"].notna()
    ]["symbol"].sort_values()

    special = None
    for symbol in delisted:
        try:
            if not get_ohlcv(symbol, start="2015-01-01", end="2021-12-31", fields=("open",)).empty:
                special = str(symbol)
                break
        except ValueError:
            continue
    assert special is not None, "real-data sample must include a delisted stock with IS data"

    rng = np.random.default_rng(67)
    pool = [symbol for symbol in universe if symbol != special]
    picked = rng.choice(pool, size=n - 1, replace=False).tolist()
    return [special, *sorted(str(symbol) for symbol in picked)]


@pytest.mark.integration
def test_get_ohlcv_batch_real_matches_single_paths() -> None:
    symbols = _real_sample_with_delisted()

    for adjust in ("qfq", "hfq", "raw"):
        batch = get_ohlcv_batch(
            symbols,
            start="2015-01-01",
            end="2021-12-31",
            adjust=adjust,
            fields=_ALL_FIELDS,
        )
        for symbol in symbols:
            try:
                expected = get_ohlcv(
                    symbol,
                    start="2015-01-01",
                    end="2021-12-31",
                    adjust=adjust,
                    fields=_ALL_FIELDS,
                )
            except ValueError:
                assert symbol not in set(batch["symbol"])
                continue

            got = batch[batch["symbol"].eq(symbol)].drop(columns=["symbol"]).set_index("date")
            pd.testing.assert_frame_equal(got, expected, check_exact=True)
