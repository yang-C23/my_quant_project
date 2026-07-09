from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from quant.data import api as data_api
from quant.data import universe as universe_mod
from quant.etl.qlib_dump import dump_cn_daily

FIXTURES = Path(__file__).parent.parent / "fixtures"


@dataclass(frozen=True)
class _Settings:
    staging_dir: Path
    qlib_cn_daily_uri: Path
    qlib_us_daily_uri: Path


def _patch_settings(monkeypatch, staging_dir: Path, qlib_dir: Path) -> None:
    settings = _Settings(
        staging_dir=staging_dir, qlib_cn_daily_uri=qlib_dir, qlib_us_daily_uri=qlib_dir
    )
    monkeypatch.setattr(data_api, "get_settings", lambda: settings)
    monkeypatch.setattr(universe_mod, "get_settings", lambda: settings)
    data_api._INIT_STATE = None


def test_get_ohlcv_adjust_identities(monkeypatch, tmp_path: Path) -> None:
    staging = FIXTURES / "staging_mini"
    qlib_dir = tmp_path / "qlib"
    dump_cn_daily(staging, qlib_dir)
    _patch_settings(monkeypatch, staging, qlib_dir)

    hfq = data_api.get_ohlcv("sh600000", adjust="hfq")
    raw = data_api.get_ohlcv("sh600000", adjust="raw")
    qfq = data_api.get_ohlcv("sh600000", adjust="qfq")
    latest_factor = float(hfq["factor"].dropna().iloc[-1])

    for col in ("open", "high", "low", "close"):
        np.testing.assert_allclose(raw[col] * raw["factor"], hfq[col], rtol=1e-6)
        np.testing.assert_allclose(qfq[col], hfq[col] / latest_factor, rtol=1e-6)
    np.testing.assert_allclose(raw["volume"] / raw["factor"], hfq["volume"], rtol=1e-6)
    assert isinstance(hfq.index, pd.DatetimeIndex)
    assert hfq.index.name == "date"


def test_get_ohlcv_batch_matches_single_symbol_paths(monkeypatch, tmp_path: Path) -> None:
    staging = FIXTURES / "staging_mini"
    qlib_dir = tmp_path / "qlib"
    dump_cn_daily(staging, qlib_dir)
    _patch_settings(monkeypatch, staging, qlib_dir)

    symbols = ["sh600000", "sh688001"]
    fields = ("open", "high", "low", "close", "volume", "amount", "factor")
    for adjust in ("qfq", "hfq", "raw"):
        batch = data_api.get_ohlcv_batch(symbols, adjust=adjust, fields=fields)
        for symbol in symbols:
            got = batch[batch["symbol"].eq(symbol)].drop(columns=["symbol"]).set_index("date")
            expected = data_api.get_ohlcv(symbol, adjust=adjust, fields=fields)
            pd.testing.assert_frame_equal(got, expected, check_exact=True)


def test_get_features_multi_symbol(monkeypatch, tmp_path: Path) -> None:
    staging = FIXTURES / "staging_mini"
    qlib_dir = tmp_path / "qlib"
    dump_cn_daily(staging, qlib_dir)
    _patch_settings(monkeypatch, staging, qlib_dir)

    got = data_api.get_features(["sh600000", "sh688001"], ["close", "factor"])

    assert {"$close", "$factor"}.issubset(got.columns)
    assert set(got.index.get_level_values("instrument")) == {"SH600000", "SH688001"}


def test_list_symbols_filters_staging_pit_and_mktcap(monkeypatch, tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    securities = pd.DataFrame(
        {
            "symbol": ["sh600000", "sh688001", "sz200001", "bj830799", "sh510050"],
            "name": [None] * 5,
            "exchange": ["sh", "sh", "sz", "bj", "sh"],
            "sec_type": ["stock", "stock", "stock", "stock", "etf"],
            "board": ["main", "star", "b", "bse", "etf"],
            "list_date": pd.to_datetime(
                ["2020-01-01", "2020-01-01", "2020-01-01", "2020-01-01", "2020-01-01"]
            ),
            "delist_date": [pd.NaT, pd.NaT, pd.NaT, pd.Timestamp("2021-01-10"), pd.NaT],
        }
    )
    basics = pd.DataFrame(
        {
            "symbol": ["sh600000", "sz200001", "bj830799"],
            "date": pd.to_datetime(["2021-01-05"] * 3),
            "float_mktcap": [60e8, 20e8, 80e8],
        }
    )
    securities.to_parquet(staging / "securities.parquet", index=False)
    basics.to_parquet(staging / "basics.parquet", index=False)
    _patch_settings(monkeypatch, staging, tmp_path / "qlib")

    assert universe_mod.list_symbols(at="2021-01-05") == ["bj830799", "sh600000", "sz200001"]
    assert universe_mod.list_symbols(exclude_boards={"star", "b", "bse"}, at="2021-01-05") == [
        "sh600000"
    ]
    assert universe_mod.list_symbols(at="2022-01-01") == ["sh600000", "sz200001"]
    assert universe_mod.list_symbols(min_float_mktcap=50e8, at="2021-01-05") == [
        "bj830799",
        "sh600000",
    ]
