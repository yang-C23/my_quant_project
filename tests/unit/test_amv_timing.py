from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.indicators.amv import amv
from quant.research.amv_timing import (
    build_variant_signal,
    evaluate_timing,
    right_side_cost,
    verify_k_invariance,
)


def _index_frame() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=8, freq="D")
    close = [100.0, 110.0, 121.0, 108.9, 119.79, 113.8005, 125.18055, 131.4395775]
    return pd.DataFrame(
        {
            "open": close,
            "high": [item * 1.01 for item in close],
            "low": [item * 0.99 for item in close],
            "close": close,
            "volume": [1_000.0] * len(close),
            "amount": [10_000_000.0] * len(close),
        },
        index=dates,
    )


def test_evaluate_timing_regime_returns_drawdown_and_waves() -> None:
    close = _index_frame()["close"]
    signal = pd.DataFrame({"regime": [0, 1, 1, 0, 1, 1, 1, 0]}, index=close.index)

    got = evaluate_timing(pd.DataFrame(index=close.index), signal, close)

    assert got.wave_count == 2
    assert got.wave_returns[0] == pytest.approx(-0.01)
    assert got.wave_returns[1] == pytest.approx(0.09725)
    assert got.cumulative_return == pytest.approx(0.0862775)
    assert got.win_rate == 0.5
    assert got.profit_factor == pytest.approx(9.725)
    assert got.max_drawdown == pytest.approx(-0.145)


def test_k_factor_does_not_change_amv_pct() -> None:
    frame = _index_frame()

    got = verify_k_invariance(frame, [1.8, 2.13, 2.6])

    assert got["max_abs_pct_diff"].fillna(0.0).max() < 1e-10


def test_confirm_2d_enters_one_bar_later_after_positive_amv_pct() -> None:
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    amv_df = pd.DataFrame(
        {
            "amv_pct": [4.5, 1.0, -1.0, -3.0, 5.0],
            "amv_close": [10.0, 10.1, 10.0, 9.7, 10.2],
            "amv_life": [9.0] * 5,
        },
        index=dates,
    )
    close = pd.Series([100.0, 102.0, 101.0, 98.0, 103.0], index=dates)

    got = build_variant_signal(amv_df, close, buy_th=4.0, sell_th=-2.3, variant="confirm_2d")

    assert got["sig_amv_buy"].tolist() == [False, True, False, False, False]
    assert got["regime"].tolist() == [0, 1, 1, 0, 0]


def test_right_side_cost_counts_missed_and_avoided_false_entries() -> None:
    close = pd.Series(
        [100.0, 102.0, 104.0, 103.0, 98.0, 101.0],
        index=pd.date_range("2020-01-01", periods=6, freq="D"),
    )
    immediate = pd.DataFrame({"regime": [1, 1, 0, 1, 1, 0]}, index=close.index)
    variant = pd.DataFrame({"regime": [0, 1, 1, 0, 0, 0]}, index=close.index)

    got = right_side_cost(immediate, variant, close)

    assert got["base_entries"] == 2.0
    assert got["confirmed_entries"] == 1.0
    assert got["missed_return_avg"] == pytest.approx(0.02)
    assert got["avoided_false"] == 1.0


def test_amv_smoke_with_variant_signal() -> None:
    frame = _index_frame()
    amv_df = amv(frame)
    signal = build_variant_signal(
        amv_df, frame["close"], buy_th=2.0, sell_th=-2.0, variant="immediate"
    )

    assert signal.index.equals(frame.index)
    assert not np.isinf(signal["regime"].to_numpy(dtype=float)).any()
