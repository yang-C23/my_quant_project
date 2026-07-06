"""Vectorized TDX (通达信) primitive functions, 1:1 semantics.

Contract: docs/indicators/README.md (semantics table + NaN policy).
All functions are pure ``pd.Series -> pd.Series`` over a single symbol
sorted by date. Warmup positions are NaN; recursive functions (EMA/SMA)
seed from the first valid value, skip interior NaNs while holding state,
and output the held value at NaN positions (kdj.md "保持前值").

Note vs the v1 backtrader reference (tests/reference/bt_legacy): bt seeds
recursions with 0.0 during leading-NaN warmup, so early bars differ and
converge geometrically; golden tests compare after the convergence window
(see tests/unit/test_tdx_functions.py).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _as_float(x: pd.Series) -> pd.Series:
    return x.astype(float)


def _cond_to_bool(cond: pd.Series) -> pd.Series:
    """Coerce a condition series to plain bool; NaN/NA counts as False."""
    return cond.astype("boolean").fillna(False).astype(bool)


def REF(x: pd.Series, n: int) -> pd.Series:
    """Value of *x* N bars ago."""
    return x.shift(n)


def MA(x: pd.Series, n: int) -> pd.Series:
    """Simple moving average over the last N bars (NaN until N bars seen)."""
    return x.rolling(n).mean()


def _recursive_smooth(x: pd.Series, alpha: float) -> pd.Series:
    """TDX-style exponential recursion: y = alpha*x + (1-alpha)*y_prev.

    Seed = first valid value; interior NaNs hold state and echo the held
    value; leading NaNs stay NaN. Vectorized via compact-ewm-reindex.
    """
    valid = x.dropna()
    if valid.empty:
        return pd.Series(np.nan, index=x.index, dtype=float)
    smoothed = valid.astype(float).ewm(alpha=alpha, adjust=False).mean()
    return smoothed.reindex(x.index).ffill()


def EMA(x: pd.Series, n: int) -> pd.Series:
    """TDX EMA: y = (2*x + (n-1)*y') / (n+1), seeded from the first valid x."""
    return _recursive_smooth(x, alpha=2.0 / (n + 1.0))


def SMA(x: pd.Series, n: int, m: int) -> pd.Series:
    """TDX SMA(X,N,M): y = (m*x + (n-m)*y') / n, seeded from the first valid x."""
    if not 0 < m <= n:
        raise ValueError(f"SMA requires 0 < m <= n, got n={n}, m={m}")
    return _recursive_smooth(x, alpha=m / float(n))


def HHV(x: pd.Series, n: int) -> pd.Series:
    """Highest value over the last N bars; N=0 means since the first bar."""
    return x.expanding().max() if n == 0 else x.rolling(n).max()


def LLV(x: pd.Series, n: int) -> pd.Series:
    """Lowest value over the last N bars; N=0 means since the first bar."""
    return x.expanding().min() if n == 0 else x.rolling(n).min()


def SUM(x: pd.Series, n: int) -> pd.Series:
    """Rolling sum over the last N bars; N=0 means cumulative sum."""
    return x.expanding().sum() if n == 0 else x.rolling(n).sum()


def COUNT(cond: pd.Series, n: int) -> pd.Series:
    """How many of the last N bars satisfy *cond* (NaN condition counts as False)."""
    filled = _as_float(_cond_to_bool(cond))
    return filled.expanding().sum() if n == 0 else filled.rolling(n).sum()


def CROSS(a: pd.Series, b: pd.Series) -> pd.Series:
    """A crosses above B: A_t > B_t and A_{t-1} <= B_{t-1} (NaN -> False)."""
    above = a > b
    below_prev = (a.shift(1) <= b.shift(1)).fillna(False)
    return (above & below_prev).astype(bool)


def BARSLAST(cond: pd.Series) -> pd.Series:
    """Bars since *cond* was last True (0 on the True bar; NaN before any True)."""
    idx = np.arange(len(cond), dtype=float)
    marks = pd.Series(np.where(_cond_to_bool(cond).to_numpy(), idx, np.nan), index=cond.index)
    return pd.Series(idx, index=cond.index) - marks.ffill()


def EVERY(cond: pd.Series, n: int) -> pd.Series:
    """True when *cond* held on all of the last N bars."""
    return COUNT(cond, n) == n


def EXIST(cond: pd.Series, n: int) -> pd.Series:
    """True when *cond* held on any of the last N bars."""
    return COUNT(cond, n) >= 1


def IIF(cond: pd.Series, a: pd.Series | float, b: pd.Series | float) -> pd.Series:
    """TDX IF(cond, a, b); NaN condition selects *b* (matches bt.If's NaN==False)."""
    chosen = np.where(_cond_to_bool(cond).to_numpy(), a, b)
    return pd.Series(chosen, index=cond.index, dtype=float)


def MAX2(a: pd.Series | float, b: pd.Series | float) -> pd.Series:
    """Pointwise maximum (TDX MAX)."""
    return np.maximum(a, b)


def MIN2(a: pd.Series | float, b: pd.Series | float) -> pd.Series:
    """Pointwise minimum (TDX MIN)."""
    return np.minimum(a, b)


def ABS_(x: pd.Series) -> pd.Series:
    """Pointwise absolute value (TDX ABS)."""
    return x.abs()
