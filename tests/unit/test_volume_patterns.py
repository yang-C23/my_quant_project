from __future__ import annotations

import pandas as pd

from quant.indicators.volume_patterns import single_needle_proxy, volume_patterns
from quant.signals import registry


def _bars(
    close: list[float],
    *,
    open_: list[float] | None = None,
    low: list[float] | None = None,
    volume: list[float] | None = None,
) -> pd.DataFrame:
    open_values = open_ if open_ is not None else close
    low_values = (
        low
        if low is not None
        else [min(o, c) - 0.1 for o, c in zip(open_values, close, strict=True)]
    )
    high_values = [max(o, c) + 0.1 for o, c in zip(open_values, close, strict=True)]
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


def test_dvy_sandwich_accepts_two_or_three_pullback_days_not_four() -> None:
    two_day = _bars(
        close=[10.0, 11.0, 10.7, 10.4, 11.0],
        open_=[9.9, 10.5, 10.9, 10.6, 10.5],
        volume=[100.0, 220.0, 120.0, 80.0, 170.0],
    )
    four_day = _bars(
        close=[10.0, 11.0, 10.7, 10.5, 10.3, 10.1, 10.8],
        open_=[9.9, 10.5, 10.9, 10.7, 10.5, 10.3, 10.4],
        volume=[100.0, 220.0, 120.0, 100.0, 90.0, 80.0, 170.0],
    )

    got_two = volume_patterns(two_day)
    got_four = volume_patterns(four_day)

    assert got_two["sig_dvy_sandwich"].iloc[4]
    assert not got_four["sig_dvy_sandwich"].iloc[6]


def test_triple_dvy_requires_three_consecutive_volume_and_price_up() -> None:
    ok = _bars(
        close=[10.0, 11.0, 12.0, 13.0],
        open_=[9.8, 10.5, 11.5, 12.5],
        volume=[100.0, 200.0, 400.0, 800.0],
    )
    price_break = _bars(
        close=[10.0, 11.0, 10.5, 13.0],
        open_=[9.8, 10.5, 10.2, 12.5],
        volume=[100.0, 200.0, 400.0, 800.0],
    )

    assert volume_patterns(ok)["sig_triple_dvy"].iloc[3]
    assert not volume_patterns(price_break)["sig_triple_dvy"].iloc[3]


def test_zero_previous_volume_does_not_emit_double_volume() -> None:
    df = _bars(
        close=[10.0, 10.5],
        open_=[9.9, 10.0],
        volume=[0.0, 1.0],
    )

    got = volume_patterns(df)

    assert not got["sig_double_vol_yang"].iloc[1]


def test_half_down_dead_volume_and_washout_area() -> None:
    df = _bars(
        close=[10.0] * 59 + [9.5],
        open_=[10.0] * 59 + [10.0],
        volume=[100.0] * 59 + [50.0],
    )

    got = volume_patterns(df)

    assert got["sig_half_down"].iloc[59]
    assert got["sig_dead_vol"].iloc[59]
    assert got["washout_area_ratio"].iloc[59] > 0


def test_single_needle_proxy_shape_and_docstring() -> None:
    assert "not equivalent" in (single_needle_proxy.__doc__ or "")

    df = _bars(
        close=[10.0] * 24 + [10.2],
        open_=[10.0] * 24 + [10.4],
        low=[9.4] * 24 + [9.5],
        volume=[100.0] * 24 + [50.0],
    )
    high_volume = df.copy()
    high_volume.loc[24, "volume"] = 60.0

    got = single_needle_proxy(df)
    failed = single_needle_proxy(high_volume)

    assert got["sig_single_needle"].iloc[24]
    assert not failed["sig_single_needle"].iloc[24]


def test_volume_pattern_registry_names() -> None:
    assert {"double_vol_yang", "triple_dvy", "single_needle_proxy"}.issubset(registry.names())
