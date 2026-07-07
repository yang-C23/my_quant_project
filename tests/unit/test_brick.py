from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.etl.staging import parse_day_bytes
from quant.indicators.brick_osc import PRESETS, BrickParams, _compose_brick_signal, brick_osc
from quant.signals import registry

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture_ohlcv(symbol: str) -> pd.DataFrame:
    buf = (FIXTURES / "tdx" / "lday" / f"{symbol}.day").read_bytes()
    return parse_day_bytes(buf, symbol).reset_index(drop=True)


def _golden(symbol: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "goldens" / f"bt_legacy_{symbol}.csv")


def _compose(
    delta: list[float],
    params: BrickParams,
    *,
    close: list[float] | None = None,
    trend: list[bool] | None = None,
    j: list[float] | None = None,
) -> pd.DataFrame:
    index = pd.RangeIndex(len(delta))
    close_s = pd.Series(close or [10.0] * (len(delta) - 1) + [10.2], index=index)
    trend_s = pd.Series(trend or [True] * len(delta), index=index)
    j_s = pd.Series(j or [50.0] * len(delta), index=index)
    delta_s = pd.Series(delta, index=index)
    zxt = pd.Series([10.0] * len(delta), index=index)
    return _compose_brick_signal(zxt, delta_s, close_s, trend_s, j_s, params)


def test_brick_presets_match_variant_table() -> None:
    assert PRESETS == {
        "strict": BrickParams(
            signal_col="sig_brick_strict",
            require_burst=True,
            oversold_mode="none",
            require_len_check=False,
            smallup_pct=0.03,
        ),
        "relaxed": BrickParams(
            signal_col="sig_brick_relaxed",
            require_burst=False,
            oversold_mode="prev",
            require_len_check=False,
            smallup_pct=0.03,
        ),
        "len_checked": BrickParams(
            signal_col="sig_brick_len",
            require_burst=False,
            oversold_mode="recent3",
            require_len_check=True,
            smallup_pct=0.04,
        ),
    }


@pytest.mark.parametrize("symbol", ["sh600000", "sz000001"])
def test_brick_zxt_matches_bt_golden(symbol: str) -> None:
    df = _fixture_ohlcv(symbol)
    got = brick_osc(df)
    golden = _golden(symbol)

    np.testing.assert_allclose(got["zxt"], golden["brick"], rtol=1e-8, atol=1e-8, equal_nan=True)
    pd.testing.assert_series_equal(
        got["sig_brick_turn"],
        golden["brick_xg"].fillna(0).astype(bool),
        check_names=False,
    )


def test_brick_strict_turn_strong_burst_and_smallup_edges() -> None:
    params = PRESETS["strict"]
    ok = _compose([0.0, -1.0, -2.0, -1.0, -0.5, 1.8], params)
    weak = _compose([0.0, -1.0, -2.0, -1.0, -0.5, 0.2], params)
    large_up = _compose(
        [0.0, -1.0, -2.0, -1.0, -0.5, 1.8],
        params,
        close=[10.0, 10.0, 10.0, 10.0, 10.0, 10.5],
    )
    no_turn = _compose([0.0, -1.0, -2.0, -1.0, 0.5, 1.8], params)

    assert ok["sig_brick_turn"].iloc[5]
    assert ok["brick_strong"].iloc[5]
    assert ok["brick_burst"].iloc[5]
    assert ok["sig_brick_strict"].iloc[5]
    assert not weak["brick_strong"].iloc[5]
    assert not weak["sig_brick_strict"].iloc[5]
    assert not large_up["brick_smallup"].iloc[5]
    assert not large_up["sig_brick_strict"].iloc[5]
    assert not no_turn["sig_brick_turn"].iloc[5]


def test_brick_relaxed_requires_previous_j_oversold_without_burst() -> None:
    params = PRESETS["relaxed"]
    ok = _compose([0.0, -1.0, -2.0, -1.0, -0.5, 0.5], params, j=[50, 50, 50, 50, 12, 50])
    no_osd = _compose([0.0, -1.0, -2.0, -1.0, -0.5, 0.5], params, j=[50, 50, 50, 50, 20, 50])

    assert ok["sig_brick_relaxed"].iloc[5]
    assert not no_osd["brick_oversold"].iloc[5]
    assert not no_osd["sig_brick_relaxed"].iloc[5]


def test_brick_len_checks_green_red_length_and_recent3_oversold() -> None:
    params = PRESETS["len_checked"]
    ok = _compose([0.0, -1.0, -2.0, -1.0, -3.0, 2.1], params, j=[50, 50, 12, 50, 50, 50])
    small_green = _compose([0.0, -1.0, -2.0, -1.0, -0.2, 1.5], params, j=[50, 50, 12, 50, 50, 50])
    small_red = _compose([0.0, -1.0, -2.0, -1.0, -3.0, 0.5], params, j=[50, 50, 12, 50, 50, 50])

    assert ok["brick_gok"].iloc[5]
    assert ok["brick_rok"].iloc[5]
    assert ok["brick_oversold"].iloc[5]
    assert ok["sig_brick_len"].iloc[5]
    assert not small_green["brick_gok"].iloc[5]
    assert not small_green["sig_brick_len"].iloc[5]
    assert not small_red["brick_rok"].iloc[5]
    assert not small_red["sig_brick_len"].iloc[5]


def test_long_fixture_brick_signal_snapshot_and_registry() -> None:
    df = _fixture_ohlcv("sz000001_long")
    got = {
        name: df.loc[brick_osc(df, params)[params.signal_col], "date"].astype(str).tolist()
        for name, params in PRESETS.items()
    }

    assert got == {
        "strict": ["2022-12-09", "2022-12-27", "2023-03-01", "2023-03-15"],
        "relaxed": ["2023-02-09", "2023-02-14", "2023-03-15"],
        "len_checked": [],
    }
    assert {"brick_strict", "brick_relaxed", "brick_len"}.issubset(registry.names())
