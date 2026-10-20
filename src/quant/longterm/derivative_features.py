"""Causal empirical derivative pressure proxies; no claim to observe forced liquidation."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd


def nominal_expiry(symbol: str) -> pd.Timestamp:
    """Third Friday by contract month; holiday-adjusted contracts require separate proof."""
    match = re.match(r"^[A-Z]+(\d{2})(\d{2})", symbol)
    if not match:
        raise ValueError("unknown contract identifier")
    first = pd.Timestamp(2000 + int(match[1]), int(match[2]), 1)
    return first + pd.Timedelta(days=(4 - first.dayofweek) % 7 + 14)


def seasonal_rank(values: pd.Series, *, years: int, radius: int, minimum: int) -> pd.Series:
    """Compare only strictly prior, similar-season observations of a constant tenor."""
    out = pd.Series(np.nan, index=values.index)
    first = values.first_valid_index()
    if first is None:
        return out
    for i, (date, value) in enumerate(values.items()):
        if pd.isna(value) or date < first + pd.DateOffset(years=years):
            continue
        history = values.iloc[:i].loc[date - pd.DateOffset(years=years) :].dropna()
        distance = np.abs(history.index.dayofyear.to_numpy() - date.dayofyear)
        history = history[np.minimum(distance, 366 - distance) <= radius]
        if len(history) >= minimum:
            out.iloc[i] = ((history < value).sum() + 0.5 * (history == value).sum()) / len(history)
    return out


def futures_basis_features(
    contracts: pd.DataFrame,
    spot: pd.Series,
    prefix: str,
    config: dict,
    *,
    expiry_calendar: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, dict]:
    """Thirty-day bracketed futures basis with seasonality, not an invented fair value.

    No expired contract, main-contract hindsight, or tenor extrapolation. Earlier
    futures closes differ from the cash-market close and are excluded. Holidays
    shifting a third-Friday expiry are excluded without verified expiry notices.
    Interest and expected dividends are not observed here; the output remains an
    empirical seasonal proxy and cannot be called fully carry-adjusted basis.
    """
    source = contracts[contracts.symbol.str.fullmatch(prefix + r"\d{4}")].copy()
    source["date"] = pd.to_datetime(source.date)
    source["expiry"] = source.symbol.map(nominal_expiry)
    source["days_to_expiry"] = (source.expiry - source.date).dt.days
    excluded_expiry = ~source.expiry.isin(expiry_calendar)
    excluded_early = source.date < pd.Timestamp(config["first_aligned_close"])
    source = source[~excluded_expiry & ~excluded_early]
    source = source[source.volume.gt(0) & source.close.gt(0) & source.days_to_expiry.gt(0)]
    if source.duplicated(["symbol", "date"]).any():
        raise ValueError("duplicate futures observations")
    target = config["target_calendar_days"]
    rows = []
    for date, group in source.groupby("date", sort=True):
        if date not in spot.index:
            continue
        group = group.sort_values("days_to_expiry")
        below = group[group.days_to_expiry <= target]
        above = group[group.days_to_expiry >= target]
        if below.empty or above.empty:
            continue
        lo, hi = below.iloc[-1], above.iloc[0]
        weight = (
            (target - lo.days_to_expiry) / (hi.days_to_expiry - lo.days_to_expiry)
            if hi.days_to_expiry != lo.days_to_expiry
            else 0.0
        )
        synthetic = (1 - weight) * lo.close + weight * hi.close
        rows.append(
            {
                "date": date,
                "basis_30d": synthetic / spot.loc[date] - 1,
                "near_contract": lo.symbol,
                "far_contract": hi.symbol,
                "near_days": int(lo.days_to_expiry),
                "far_days": int(hi.days_to_expiry),
                "far_weight": float(weight),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(index=spot.index), {"reason": "no_verified_bracketing_contracts"}
    frame = frame.set_index("date").reindex(spot.index)
    frame["basis_percentile"] = seasonal_rank(
        frame.basis_30d,
        years=config["historical_window_years"],
        radius=config["seasonal_window_calendar_days"],
        minimum=config["minimum_prior_observations"],
    )
    return frame, {
        "contract_rows": len(contracts),
        "excluded_unknown_or_holiday_expiry": int(excluded_expiry.sum()),
        "excluded_unsynchronized_early_close": int(excluded_early.sum()),
        "constant_tenor_dates": int(frame.basis_30d.notna().sum()),
        "ranked_dates": int(frame.basis_percentile.notna().sum()),
        "classification": "empirical_seasonal_not_fully_carry_adjusted",
    }


def options_activity_features(
    contracts: pd.DataFrame,
    spot: pd.Series,
    prefix: str,
    config: dict,
    *,
    expiry_calendar: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, dict]:
    """Fixed reported-Delta/maturity premium activity; missing quotes never become zero.

    Turnover units are checked against price*contracts*100. This cannot reconstruct
    bid/ask spreads, intraday 0DTE activity, opening/closing trades or dealer direction.
    """
    source = contracts[contracts.symbol.str.match(prefix + r"\d{4}-[CP]-")].copy()
    if source.empty:
        return pd.DataFrame(index=spot.index), {"reason": "no_listed_options"}
    source["date"] = pd.to_datetime(source.date)
    source["expiry"] = source.symbol.map(nominal_expiry)
    source["days_to_expiry"] = (source.expiry - source.date).dt.days
    source["side"] = source.symbol.str.extract(r"-([CP])-", expand=False)
    source["turnover_cny"] = source.turnover_source_value * 10000
    source["vwap"] = source.turnover_cny / (source.volume.where(source.volume > 0) * 100)
    traded = source.volume.gt(0)
    valid = (
        source.expiry.isin(expiry_calendar)
        & traded
        & source.turnover_cny.gt(0)
        & source.vwap.between(source.low - 0.201, source.high + 0.201)
        & source.days_to_expiry.ge(0)
    )
    bad_trades = traded & ~source.vwap.between(source.low - 0.201, source.high + 0.201)
    observed = source[valid]
    raw_tenor = source[
        source.expiry.isin(expiry_calendar)
        & traded
        & source.days_to_expiry.between(*config["maturity_days"])
    ]
    raw_turnover = raw_tenor.groupby("date").turnover_cny.sum()
    rows = []
    lower, upper = config["maturity_days"]
    low_delta, high_delta = config["delta_abs_range"]
    for date, group in observed.groupby("date", sort=True):
        tenor = group[group.days_to_expiry.between(lower, upper)]
        if tenor.empty:
            continue
        known_delta = tenor.delta.notna() & tenor.delta.abs().le(1)
        total_turnover = tenor.turnover_cny.sum()
        delta_coverage = tenor.loc[known_delta, "turnover_cny"].sum() / total_turnover
        trade_coverage = total_turnover / raw_turnover.get(date, np.nan)
        accepted = delta_coverage >= 0.95 and trade_coverage >= 0.95
        puts = tenor.side.eq("P") & tenor.delta.between(-high_delta, -low_delta)
        calls = tenor.side.eq("C") & tenor.delta.between(low_delta, high_delta)
        deep_put_share = tenor.loc[puts, "turnover_cny"].sum() / total_turnover
        deep_call_share = tenor.loc[calls, "turnover_cny"].sum() / total_turnover
        rows.append(
            {
                "date": date,
                "deep_put_premium_share": deep_put_share if accepted else np.nan,
                "deep_call_premium_share": deep_call_share if accepted else np.nan,
                "delta_turnover_coverage": delta_coverage,
                "valid_trade_turnover_coverage": trade_coverage,
                "premium_turnover_cny": total_turnover,
                "contracts_traded": int(tenor.volume.sum()),
                "expiry_day_premium_share": (
                    group.loc[group.days_to_expiry.eq(0), "turnover_cny"].sum()
                    / group.turnover_cny.sum()
                ),
                "is_monthly_expiry": bool(group.days_to_expiry.eq(0).any()),
            }
        )
    if not rows:
        return pd.DataFrame(index=spot.index), {
            "reason": "no_usable_reported_delta_and_trade_values"
        }
    frame = pd.DataFrame(rows).set_index("date").reindex(spot.index)
    # A full two-year window, not a rolling count of a few reported extreme days.
    from quant.longterm.features import historical_percentile

    for side in ("put", "call"):
        frame[f"deep_{side}_percentile"] = historical_percentile(
            frame[f"deep_{side}_premium_share"], years=config["history_years"], positive_only=False
        )
    return frame, {
        "option_rows": len(source),
        "traded_rows": int(traded.sum()),
        "turnover_price_unit_failures": int(bad_trades.sum()),
        "usable_traded_rows": len(observed),
        "ranked_put_dates": int(frame.deep_put_percentile.notna().sum()),
        "gamma": "not_observed_no_dealer_direction",
        "zero_dte": "monthly_expiry_EOD_summary_not_US_intraday_0DTE",
        "price_surge": "unverified_without_synchronized_bid_ask",
    }


def factor_confirmation(
    stages: pd.DataFrame,
    extreme: pd.Series,
    relieved: pd.Series,
    available: pd.Series,
    *,
    confirmation: int = 5,
) -> pd.Series:
    """Each pressure event can produce one later stabilization+factor-relief signal."""
    if not all(x.index.equals(stages.index) for x in (extreme, relieved, available)):
        raise ValueError("factor decisions must share the price-stage calendar")
    result = pd.Series(False, index=stages.index)
    event, stressed, entered = None, False, False
    for date, row in stages.iterrows():
        if pd.isna(row.event_id):
            continue
        identifier = int(row.event_id)
        if identifier != event:
            event, stressed, entered = identifier, False, False
        if not available.loc[date]:
            continue
        stressed |= bool(extreme.loc[date])
        stable = row.sessions_since_event_low >= confirmation and row.close > row.sma_10
        if stressed and not entered and stable and bool(relieved.loc[date]):
            result.loc[date], entered = True, True
    return result
