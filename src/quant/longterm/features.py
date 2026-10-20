"""Causal features; missing historical evidence never becomes a cheap signal."""

from __future__ import annotations

import numpy as np
import pandas as pd


def historical_percentile(
    observations: pd.Series,
    *,
    years: int = 10,
    expanding: bool = False,
    minimum_coverage: float = 0.8,
    positive_only: bool = True,
) -> pd.Series:
    """Midrank current value against strictly earlier dates in a calendar-year window.

    A daily series needs a full calendar warmup and >=80% of 252*years valid
    observations. Ties receive half weight. Inputs must already be PIT-aligned.
    """
    values = observations.copy().astype(float)
    if not isinstance(values.index, pd.DatetimeIndex) or not values.index.is_monotonic_increasing:
        raise ValueError("observations require an increasing DatetimeIndex")
    if not values.index.is_unique or years < 1 or not 0 < minimum_coverage <= 1:
        raise ValueError("invalid percentile configuration or duplicate dates")
    values = values.where(np.isfinite(values))
    if positive_only:
        values = values.where(values > 0)
    result = pd.Series(np.nan, index=values.index, dtype=float)
    if values.empty:
        return result
    first_valid = values.first_valid_index()
    if first_valid is None:
        return result
    minimum = int(252 * years * minimum_coverage)
    for i, (date, value) in enumerate(values.items()):
        if pd.isna(value) or date < first_valid + pd.DateOffset(years=years):
            continue
        left = 0 if expanding else values.index.searchsorted(date - pd.DateOffset(years=years))
        history = values.iloc[left:i].dropna()
        if len(history) >= minimum:
            result.iloc[i] = ((history < value).sum() + (history == value).sum() * 0.5) / len(
                history
            )
    return result


def align_available(
    observations: pd.DataFrame,
    decisions: pd.DatetimeIndex,
    column: str,
    *,
    maximum_age_days: int = 7,
) -> pd.Series:
    """As-of join on publication time, never the economic observation date alone."""
    required = {"date", "available_at", column}
    if not required.issubset(observations):
        raise ValueError("publication timestamps and observation dates are required")
    if decisions.tz is None:
        raise ValueError("decision times must have an explicit timezone")
    if not decisions.is_monotonic_increasing or not decisions.is_unique:
        raise ValueError("decision times must be unique and increasing")
    left = pd.DataFrame({"decision_at": decisions.tz_convert("UTC").as_unit("ns")})
    right = observations.copy()
    # Arrow stores UTC microseconds; pandas-generated trading calendars often
    # use nanoseconds. merge_asof requires the same physical datetime resolution.
    right["available_at"] = pd.to_datetime(right["available_at"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    right["date"] = pd.to_datetime(right["date"], utc=True).astype("datetime64[ns, UTC]")
    right = right.sort_values(["available_at", "date"])
    # A late revision of an older observation must not replace a newer known value.
    # Revisions of the latest economic date remain eligible from their release time.
    right = right[right["date"].eq(right["date"].cummax())]
    merged = pd.merge_asof(
        left.sort_values("decision_at"),
        right,
        left_on="decision_at",
        right_on="available_at",
        direction="backward",
    )
    age = (merged["decision_at"] - merged["date"]).dt.total_seconds() / 86400
    return pd.Series(
        merged[column].where(age.between(0, maximum_age_days)).to_numpy(), index=decisions
    )


def valuation_temperature(
    frame: pd.DataFrame, metric: str, *, years: int = 10, expanding: bool = False
) -> pd.Series:
    """All temperatures run from cheap=0 to expensive=1; units are decimal yields."""
    if metric in {"pe", "pb"}:
        values, invert, positive = frame[metric], False, True
    elif metric == "earnings_yield":
        values, invert, positive = 1 / frame["pe"].where(frame["pe"] > 0), True, True
    elif metric == "earnings_yield_spread":
        values = 1 / frame["pe"].where(frame["pe"] > 0) - frame["bond_yield"]
        invert, positive = True, False
    elif metric == "dividend_yield_spread":
        values, invert, positive = frame["dividend_yield"] - frame["bond_yield"], True, False
    elif metric == "dividend_yield":
        values, invert, positive = frame[metric], True, True
    else:
        raise ValueError(f"unsupported valuation metric: {metric}")
    ranks = historical_percentile(values, years=years, expanding=expanding, positive_only=positive)
    return 1 - ranks if invert else ranks


def price_features(
    bars: pd.DataFrame,
    *,
    drawdown: float = 0.20,
    sigma: float = 2.0,
    confirmation: int = 5,
    event_window: int = 20,
) -> pd.DataFrame:
    """Prior-60-day volatility, 252-session drawdown, KDJ and clustered panic events.

    KDJ uses RSV(9), K/D recursive 1/3 smoothing initialized at 50. Flat ranges
    retain RSV=50. Stabilization means no new post-event low for five sessions,
    and close above SMA(10), within 20 sessions. All operations are causal.
    """
    if not bars.index.is_monotonic_increasing or not bars.index.is_unique:
        raise ValueError("bars must have unique increasing dates")
    close = bars["close"].astype(float)
    returns = close.pct_change(fill_method=None)
    volatility = returns.shift(1).rolling(60, min_periods=60).std(ddof=1)
    out = pd.DataFrame(index=bars.index)
    out["drawdown_252"] = close / close.rolling(252, min_periods=252).max() - 1
    out["return_5"] = close.pct_change(5, fill_method=None)
    out["volatility_60"] = volatility
    out["panic"] = (
        (out["drawdown_252"] <= -drawdown)
        & (out["return_5"] <= -sigma * volatility * np.sqrt(5))
        & (volatility > 0)
    )
    out["panic_event"] = False
    out["stabilized"] = False
    out["event_id"] = pd.Series(pd.NA, index=bars.index, dtype="Int64")
    sma = close.rolling(10, min_periods=10).mean()
    low = bars["low"].astype(float) if "low" in bars else close
    event_start, last_panic, last_low, event_id = None, -event_window, 0, 0
    low_water = np.inf
    for i in range(len(out)):
        if out["panic"].iloc[i] and i - last_panic >= event_window:
            event_start, last_low = i, i
            low_water = low.iloc[i]
            event_id += 1
            out.iloc[i, out.columns.get_loc("panic_event")] = True
        if out["panic"].iloc[i]:
            last_panic = i
        if event_start is None:
            continue
        out.iloc[i, out.columns.get_loc("event_id")] = event_id
        if i - event_start > event_window:
            event_start = None
            continue
        if low.iloc[i] < low_water:
            low_water, last_low = low.iloc[i], i
        if i - last_low >= confirmation and close.iloc[i] > sma.iloc[i]:
            out.iloc[i, out.columns.get_loc("stabilized")] = True
            event_start = None
    if {"high", "low"}.issubset(bars):
        ll = bars["low"].rolling(9, min_periods=9).min()
        hh = bars["high"].rolling(9, min_periods=9).max()
        rsv = ((close - ll) / (hh - ll).replace(0, np.nan) * 100).where(hh != ll, 50)
        k, d = 50.0, 50.0
        js = []
        for value in rsv:
            if pd.isna(value):
                js.append(np.nan)
            else:
                k, d = (2 * k + value) / 3, (2 * d + (2 * k + value) / 3) / 3
                js.append(3 * k - 2 * d)
        out["j"] = js
    else:
        out["j"] = np.nan  # close-only series cannot support a genuine KDJ calculation
    return out


def select_etf(history: pd.DataFrame, decision_date: str, index_id: str) -> str | None:
    """Choose using only earlier 60 sessions; includes delisted historical products."""
    required = {"date", "symbol", "index_id", "amount", "leveraged", "listed_at"}
    if not required.issubset(history):
        raise ValueError("historical membership, listing and turnover metadata are required")
    cutoff = pd.Timestamp(decision_date)
    frame = history[
        (pd.to_datetime(history["date"]) < cutoff)
        & (history["index_id"] == index_id)
        & ~history["leveraged"]
    ].copy()
    last_market_date = pd.to_datetime(frame["date"]).max()
    candidates = []
    for symbol, group in frame.groupby("symbol"):
        valid = group[pd.to_datetime(group["date"]) >= pd.to_datetime(group["listed_at"])]
        sample = valid.sort_values("date").tail(60)
        active = len(sample) > 0 and pd.to_datetime(sample["date"]).max() == last_market_date
        if "delisted_at" in sample:
            active = (
                active
                and (
                    sample["delisted_at"].isna() | (pd.to_datetime(sample["delisted_at"]) > cutoff)
                ).all()
            )
        if active and len(sample) == 60 and sample["amount"].notna().all():
            candidates.append((float(sample["amount"].sum()), str(symbol)))
    return sorted(candidates, key=lambda row: (-row[0], row[1]))[0][1] if candidates else None
