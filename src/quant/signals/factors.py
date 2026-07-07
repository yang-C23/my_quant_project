"""Signal-level factor wrappers and universe filters."""

from __future__ import annotations

import pandas as pd

from quant.indicators.b1 import B1Params, b1


def b1_signal_with_universe(
    df: pd.DataFrame, params: B1Params, *, min_float_mktcap: float = 50e8
) -> pd.Series:
    """Return B1 signal with optional universe-side market-cap filtering.

    The indicator itself does not implement MVOK or board exclusions. When
    ``float_mktcap`` is present, this wrapper applies ``float_mktcap >=
    min_float_mktcap``. Board filters belong to the caller's universe layer.
    """
    signal = b1(df, params)["sig_b1"]
    if "float_mktcap" not in df.columns:
        return signal
    return signal & df["float_mktcap"].astype(float).ge(min_float_mktcap).fillna(False)
