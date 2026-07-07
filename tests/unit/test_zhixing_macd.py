from __future__ import annotations

import numpy as np
import pandas as pd

from quant.indicators.zhixing_macd import zhixing_macd
from quant.signals import registry


def test_zhixing_macd_matches_adjust_false_ewm() -> None:
    close = pd.Series([10.0, 10.2, 10.4, 10.1, 9.9, 10.3, 10.8, 10.7, 10.6])
    df = pd.DataFrame({"close": close})

    got = zhixing_macd(df)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    diff = ema12 - ema26
    dea = diff.ewm(span=9, adjust=False).mean()
    macd = 2.0 * (diff - dea)

    np.testing.assert_allclose(got["diff"], diff, rtol=1e-10)
    np.testing.assert_allclose(got["dea"], dea, rtol=1e-10)
    np.testing.assert_allclose(got["macd"], macd, rtol=1e-10)


def test_zhixing_macd_zero_axis_cross_snapshot_and_registry() -> None:
    close = pd.Series([10.0, 10.5, 11.0, 10.8, 10.0, 9.0, 8.5, 9.2, 10.2, 11.2])
    df = pd.DataFrame({"close": close})

    got = zhixing_macd(df)
    signal = registry.get("zhixing_macd_cross")(df)

    assert got.index[got["sig_diff_cross_up_zero"]].tolist() == [1, 9]
    assert got.index[got["sig_diff_cross_dn_zero"]].tolist() == [6]
    pd.testing.assert_series_equal(
        signal,
        got["sig_diff_cross_up_zero"] | got["sig_diff_cross_dn_zero"],
        check_names=False,
    )
