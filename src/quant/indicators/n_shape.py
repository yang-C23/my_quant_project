"""N-shaped rebound structure filter."""

from __future__ import annotations

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
    low = df["low"].astype(float) if "low" in df.columns else df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else df["close"].astype(float)
    out: list[bool] = []
    for end_pos in range(len(df)):
        start_pos = max(0, end_pos - lookback + 1)
        found = False
        for rebound_pos in range(start_pos + 1, end_pos):
            prior_lows = low.iloc[start_pos:rebound_pos]
            base_low = float(prior_lows.min())
            if pd.isna(base_low) or base_low <= 0:
                continue
            if float(high.iloc[rebound_pos]) < base_low * (1.0 + rebound_pct):
                continue
            pullback_lows = low.iloc[rebound_pos + 1 : end_pos + 1]
            if pullback_lows.empty:
                continue
            if float(pullback_lows.min()) >= base_low and float(pullback_lows.min()) < float(
                high.iloc[rebound_pos]
            ):
                found = True
                break
        out.append(found)
    return pd.Series(out, index=df.index, dtype=bool, name="n_shape")
