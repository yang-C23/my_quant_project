"""Geometric performance statistics and cash-flow-aware investor returns."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd


def geometric_metrics(returns: pd.Series, *, periods_per_year: float = 252.0) -> dict:
    """Compound returns, including the initial wealth peak in drawdowns."""
    values = returns.dropna().astype(float).to_numpy()
    if not len(values):
        raise ValueError("returns are empty")
    if not np.isfinite(values).all() or (values < -1).any():
        raise ValueError("returns must be finite and >= -100%")
    wealth = np.r_[1.0, np.cumprod(1.0 + values)]
    peaks = np.maximum.accumulate(wealth)
    drawdowns = wealth / peaks - 1.0
    volatility = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    underwater = 0
    longest = 0
    for value in drawdowns[1:]:
        underwater = underwater + 1 if value < -1e-12 else 0
        longest = max(longest, underwater)
    return {
        "total_return": float(wealth[-1] - 1),
        "annualized_return": float(wealth[-1] ** (periods_per_year / len(values)) - 1),
        "max_drawdown": float(drawdowns.min()),
        "annualized_volatility": volatility * math.sqrt(periods_per_year),
        "sharpe_zero_cash": (
            float(np.mean(values)) / volatility * math.sqrt(periods_per_year)
            if volatility > 0
            else None
        ),
        "longest_underwater_sessions": longest,
        "unrecovered_at_end": bool(drawdowns[-1] < -1e-12),
    }


def xirr(cashflows: Sequence[tuple[pd.Timestamp, float]]) -> float | None:
    """Annual money-weighted return for contributions and one terminal redemption.

    Unconventional cashflow patterns can have multiple roots; return None rather
    than silently selecting one.
    """
    grouped: dict[pd.Timestamp, float] = {}
    for date, value in cashflows:
        key = pd.Timestamp(date).normalize()
        grouped[key] = grouped.get(key, 0.0) + float(value)
    items = [(d, v) for d, v in sorted(grouped.items()) if v != 0]
    if len(items) < 2 or not any(v < 0 for _, v in items) or items[-1][1] <= 0:
        return None
    if any(v > 0 for _, v in items[:-1]):
        return None
    years = np.array([(d - items[0][0]).days / 365.2425 for d, _ in items])
    amounts = np.array([v for _, v in items])

    def npv_log(rate: float) -> float:
        # A common scaling leaves the root unchanged and prevents overflow.
        exponent = -rate * years
        exponent -= exponent.max()
        return float(np.dot(amounts, np.exp(exponent)))

    lo, hi = -30.0, 30.0
    if npv_log(lo) * npv_log(hi) > 0:
        return None
    for _ in range(160):
        mid = (lo + hi) / 2
        if npv_log(mid) > 0:
            lo = mid
        else:
            hi = mid
    return math.expm1((lo + hi) / 2)
