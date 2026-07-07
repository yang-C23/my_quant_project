from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quant.etl.staging import parse_day_bytes
from quant.indicators.b1 import PRESETS, B1Params, b1
from quant.signals import factors, registry
from quant.tdx import functions as F

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _bars(
    close: list[float],
    *,
    open_: list[float] | None = None,
    high: list[float] | None = None,
    low: list[float] | None = None,
    volume: list[float] | None = None,
) -> pd.DataFrame:
    open_values = open_ if open_ is not None else close
    high_values = (
        high
        if high is not None
        else [max(o, c) + 0.1 for o, c in zip(open_values, close, strict=True)]
    )
    low_values = (
        low
        if low is not None
        else [min(o, c) - 0.1 for o, c in zip(open_values, close, strict=True)]
    )
    volume_values = volume if volume is not None else [100.0] * len(close)
    return pd.DataFrame(
        {
            "open": open_values,
            "high": high_values,
            "low": low_values,
            "close": close,
            "volume": volume_values,
        }
    )


def _fixture_ohlcv(symbol: str) -> pd.DataFrame:
    buf = (FIXTURES / "tdx" / "lday" / f"{symbol}.day").read_bytes()
    return parse_day_bytes(buf, symbol).reset_index(drop=True)


def test_presets_match_b1_version_table() -> None:
    assert PRESETS == {
        "b1_v242_62": B1Params(
            yangyin_windows=((28, 1.4), (14, 2.0), (57, 1.2)),
            yangyin_mode="and3",
            cnt_bad_window=14,
            plry_long_count=3,
            three_sum_window=28,
            three_sum_min=2,
            maxvol_window=14,
            line_mult=0.995,
        ),
        "b1_v242b": B1Params(
            yangyin_windows=((57, 1.25), (14, 2.25)),
            yangyin_mode="or2",
            cnt_bad_window=21,
            plry_long_count=4,
            three_sum_window=57,
            three_sum_min=4,
            maxvol_window=28,
            line_mult=0.985,
        ),
        "b1_v242p": B1Params(
            yangyin_windows=((28, 2.25), (14, 2.75)),
            yangyin_mode="or2",
            cnt_bad_window=21,
            plry_long_count=4,
            three_sum_window=28,
            three_sum_min=3,
            maxvol_window=14,
            line_mult=0.985,
        ),
    }


def test_real_yang_real_yin_flat_boundaries() -> None:
    df = _bars(
        close=[10.0, 10.0, 9.8, 9.8],
        open_=[10.0, 9.8, 10.0, 9.8],
    )

    got = b1(df)

    assert not got["real_yang"].iloc[0]
    assert got["real_yang"].iloc[1]
    assert got["real_yin"].iloc[2]
    assert not got["real_yang"].iloc[3]
    assert not got["real_yin"].iloc[3]


def test_plry_requires_volume_ratio_positive_candle_and_ma40() -> None:
    base_close = [10.0] * 41
    base_open = [9.9] * 41

    ok = b1(_bars(base_close, open_=base_open, volume=[100.0] * 40 + [250.0]))
    low_ratio = b1(_bars(base_close, open_=base_open, volume=[100.0] * 40 + [190.0]))
    flat_candle = b1(_bars(base_close, open_=[9.9] * 40 + [10.0], volume=[100.0] * 40 + [250.0]))
    below_ma40 = b1(
        _bars(
            base_close,
            open_=base_open,
            volume=[1000.0] * 39 + [100.0, 250.0],
        )
    )

    assert ok["plry"].iloc[40]
    assert not low_ratio["plry"].iloc[40]
    assert not flat_candle["plry"].iloc[40]
    assert not below_ma40["plry"].iloc[40]


def test_half_down_requires_previous_day_not_real_yin() -> None:
    df = _bars(
        close=[10.0, 9.5, 9.0],
        open_=[10.0, 10.0, 9.5],
        volume=[100.0, 50.0, 20.0],
    )

    got = b1(df)

    assert got["real_yin"].iloc[1]
    assert got["half_down"].iloc[1]
    assert not got["half_down"].iloc[2]


def test_good_count_rejects_top15o_fd15_event() -> None:
    open_values = [10.0] * 20 + [20.0]
    close_values = [10.0] * 19 + [15.0, 14.0]
    volumes = [100.0] * 20 + [200.0]
    df = _bars(close_values, open_=open_values, volume=volumes)

    got = b1(df)

    assert not got["good_cnt_ok"].iloc[20]


def test_maxvol_bad_rejects_largest_volume_real_yin() -> None:
    df = _bars(
        close=[10.0] * 13 + [9.5],
        open_=[10.0] * 13 + [10.0],
        volume=[100.0] * 13 + [500.0],
    )

    got = b1(df)

    assert got["real_yin"].iloc[13]
    assert got["maxvol_bad"].iloc[13]
    assert not got["maxvol_ok"].iloc[13]


def test_hm_short_matches_tdx_double_recursive_sma() -> None:
    df = _fixture_ohlcv("sz000001_long")

    got = b1(df)
    want = F.SMA(F.SMA(df["close"], 40, 4), 100, 50)

    np.testing.assert_allclose(got["hm_short"], want, rtol=1e-12, equal_nan=True)


def test_long_fixture_b1_hit_dates_snapshot() -> None:
    df = _fixture_ohlcv("sz000001_long")

    got = {
        name: df.loc[b1(df, params)["sig_b1"], "date"].astype(str).tolist()
        for name, params in PRESETS.items()
    }

    assert got == {
        "b1_v242_62": ["2022-12-19", "2022-12-20", "2022-12-21"],
        "b1_v242b": [],
        "b1_v242p": [],
    }


def test_b1_registry_and_universe_float_mktcap_filter(monkeypatch) -> None:
    assert {"b1_v242_62", "b1_v242b", "b1_v242p"}.issubset(registry.names())

    def fake_b1(df: pd.DataFrame, params: B1Params) -> pd.DataFrame:
        return pd.DataFrame({"sig_b1": [True] * len(df)}, index=df.index)

    monkeypatch.setattr(factors, "b1", fake_b1)
    df = pd.DataFrame({"float_mktcap": [49e8, 50e8, 51e8]})

    filtered = factors.b1_signal_with_universe(df, PRESETS["b1_v242_62"])
    unfiltered = factors.b1_signal_with_universe(
        pd.DataFrame(index=df.index), PRESETS["b1_v242_62"]
    )

    assert filtered.tolist() == [False, True, True]
    assert unfiltered.tolist() == [True, True, True]
