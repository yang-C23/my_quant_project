"""N-shaped rebound structure filter."""

from __future__ import annotations

import numpy as np
import pandas as pd


def n_shape(df: pd.DataFrame, *, lookback: int = 60, rebound_pct: float = 0.08) -> pd.Series:
    """Return bars where a low-rebound-pullback structure exists within lookback.

    The predicate at bar ``t`` only inspects bars ``<= t``. A valid structure is:
    first low, later rebound of at least ``rebound_pct``, and a subsequent
    pullback whose low does not break the first low.
    """
    if lookback < 3:
        raise ValueError("lookback must be at least 3")
    if rebound_pct <= 0:
        raise ValueError("rebound_pct must be positive")
    low = (df["low"] if "low" in df.columns else df["close"]).astype(float).to_numpy()
    high = (df["high"] if "high" in df.columns else df["close"]).astype(float).to_numpy()
    n = len(df)
    out = np.zeros(n, dtype=bool)
    mult = 1.0 + rebound_pct
    for end_pos in range(n):
        start_pos = max(0, end_pos - lookback + 1)
        if end_pos - start_pos < 2:
            continue
        window_low = low[start_pos : end_pos + 1]
        # fmin.accumulate = pandas nanmin 语义（跳过 NaN，全 NaN 才得 NaN）
        prefix_min = np.fmin.accumulate(window_low)
        suffix_min = np.fmin.accumulate(window_low[::-1])[::-1]
        rel = np.arange(1, end_pos - start_pos)
        base = prefix_min[rel - 1]
        high_r = high[start_pos + rel]
        pull = suffix_min[rel + 1]
        ok = (
            ~np.isnan(base)
            & (base > 0)
            & ~(high_r < base * mult)
            & (pull >= base)
            & (pull < high_r)
        )
        out[end_pos] = bool(ok.any())
    return pd.Series(out, index=df.index, dtype=bool, name="n_shape")
