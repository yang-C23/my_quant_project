"""ZhiXing MACD with TDX EMA semantics."""

from __future__ import annotations

import pandas as pd

from quant.tdx import functions as F


def zhixing_macd(df: pd.DataFrame) -> pd.DataFrame:
    """Return MACD lines and zero-axis DIFF cross markers."""
    if "close" not in df.columns:
        raise KeyError("missing required columns: ['close']")

    close = df["close"].astype(float)
    diff = F.EMA(close, 12) - F.EMA(close, 26)
    dea = F.EMA(diff, 9)
    macd = 2.0 * (diff - dea)
    zero = pd.Series(0.0, index=df.index)

    return pd.DataFrame(
        {
            "diff": diff,
            "dea": dea,
            "macd": macd,
            "sig_diff_cross_up_zero": F.CROSS(diff, zero),
            "sig_diff_cross_dn_zero": F.CROSS(zero, diff),
        },
        index=df.index,
    )
