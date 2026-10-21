"""Current-price/lagged-earnings proxies, explicitly using revised monthly history."""

from dataclasses import asdict

import numpy as np
import pandas as pd

from quant.longterm.cash_pool import PoolPolicy
from quant.longterm.features import align_available
from quant.longterm.stages import StageSpec


def current_pe_temperature(
    close: pd.Series, observed: pd.DataFrame, years: int | str, lag_months: int, config: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rank today's close/lagged EPS against prior monthly proxy observations.

    EPS is still revised/interpolated Shiller data; its release time is assumed.
    The monthly-average historical reference differs from today's close and is
    disclosed. No monthly average is used as an executable trading price.
    """
    if not close.index.is_unique or not close.index.is_monotonic_increasing:
        raise ValueError("ordered unique price dates required")
    if lag_months < 1 or not np.isfinite(close).all() or (close <= 0).any():
        raise ValueError("positive prices and positive earnings lag required")
    source = observed.copy()
    source["date"] = pd.to_datetime(source.date).astype("datetime64[ns]")
    source = source[source.date >= config["first_comparable_month"]].sort_values("date")
    if source.date.duplicated().any():
        raise ValueError("multiple monthly vintages require explicit adjudication")
    source["available_at"] = (
        source.date + pd.offsets.MonthEnd(lag_months) + pd.Timedelta(hours=23, minutes=59)
    ).dt.tz_localize("UTC")
    source["release_epoch_seconds"] = (
        source.available_at.astype("datetime64[ns, UTC]").astype("int64") / 1e9
    )
    source["earnings"] = source.interpolated_earnings_12m.where(
        np.isfinite(source.interpolated_earnings_12m) & source.interpolated_earnings_12m.gt(0)
    )

    def earnings_at(decisions: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
        ttl = config["maximum_staleness_after_assumed_release_days"]
        maximum_age = lag_months * 31 + ttl
        earnings = align_available(source, decisions, "earnings", maximum_age_days=maximum_age)
        release = align_available(
            source, decisions, "release_epoch_seconds", maximum_age_days=maximum_age
        )
        ages = (decisions.as_unit("ns").asi8 / 1e9 - release.to_numpy()) / 86400
        return earnings.where(ages <= ttl).to_numpy(dtype=float), release.to_numpy(dtype=float)

    monthly_publication = pd.DatetimeIndex(
        (source.date + pd.Timedelta(hours=23, minutes=59)).dt.tz_localize("UTC")
    )
    earnings, _ = earnings_at(monthly_publication)
    monthly = pd.DataFrame(
        {
            "date": source.date.to_numpy(),
            "available_at": monthly_publication,
            "monthly_price": source.monthly_average_price.to_numpy(dtype=float),
            "lagged_earnings": earnings,
        }
    )
    monthly["pe"] = monthly.monthly_price / monthly.lagged_earnings
    monthly.loc[~np.isfinite(monthly.pe) | monthly.pe.le(0), "pe"] = np.nan
    decisions = (close.index + pd.Timedelta(hours=16)).tz_localize("America/New_York")
    earnings, release = earnings_at(decisions)
    pe = close.to_numpy(dtype=float) / earnings
    ranks, counts = np.full(len(close), np.nan), np.zeros(len(close), dtype=int)
    window = 10 if years == "expanding_10" else int(years)
    if window < 1:
        raise ValueError("positive calendar warmup required")
    first = monthly.loc[monthly.pe.notna(), "date"].min()
    for i, (date, decision) in enumerate(zip(close.index, decisions, strict=True)):
        if pd.isna(first) or date < first + pd.DateOffset(years=window):
            continue
        history = monthly[monthly.available_at < decision]
        if years != "expanding_10":
            history = history[history.date >= date - pd.DateOffset(years=window)]
        values = history.pe.dropna()
        counts[i] = len(values)
        if len(values) >= 12 * window * config["minimum_history_coverage"] and np.isfinite(pe[i]):
            ranks[i] = ((values < pe[i]).sum() + 0.5 * (values == pe[i]).sum()) / len(values)
    daily = pd.DataFrame(
        {
            "current_pe": pe,
            "known_earnings": earnings,
            "earnings_assumed_release": pd.to_datetime(release, unit="s", utc=True),
            "temperature": ranks,
            "prior_monthly_observations": counts,
        },
        index=close.index,
    )
    return daily, monthly


def current_pe_registry(config: dict, primary: dict) -> list[dict]:
    """Retain all 60 prescribed variants, including no-entry and adverse accounts."""
    rows = []

    def add(
        lag: int,
        window: int | str,
        entry: str,
        exit_style: str,
        core: float,
        *,
        label: str = "",
        neighbor: bool = False,
        **changes: object,
    ) -> None:
        policy = PoolPolicy(
            **primary["funding"],
            entry=entry,
            exit=exit_style,
            core_fraction=core,
            **(
                {
                    "buy_threshold": config["buy_threshold"],
                    "sell_threshold": config["sell_threshold"],
                }
                | changes
            ),
        )
        rows.append(
            {
                "id": f"currentpe_lag{lag}_{window}_{entry}_{exit_style}_core{core:g}{label}",
                "engine": "pool",
                "scope": "neighbor" if neighbor else "all",
                "stages": asdict(StageSpec(**primary["stages"])),
                "policy": asdict(policy),
                "metric": "pe",
                "window": window,
                "observation_lag_months": lag,
                "valuation_source": "shiller_current_price_proxy",
                "assets": ["sp500"],
            }
        )

    for lag in config["earnings_lag_months"]:
        for entry in config["entries"]:
            for exit_style in config["exits"]:
                for core in config["core_fractions"]:
                    add(lag, config["primary_window_years"], entry, exit_style, core)
        for years in config["alternative_windows"]:
            for entry in ("valuation", "value_stabilized"):
                for exit_style in config["exits"]:
                    add(lag, years, entry, exit_style, 0)
        for threshold in config["buy_neighbors"]:
            add(
                lag,
                10,
                "value_stabilized",
                "valuation_time",
                0,
                label=f"_buy{threshold:g}",
                neighbor=True,
                buy_threshold=threshold,
            )
        for threshold in config["sell_neighbors"]:
            add(
                lag,
                10,
                "valuation",
                "valuation_time",
                0,
                label=f"_sell{threshold:g}",
                neighbor=True,
                sell_threshold=threshold,
            )
        add(
            lag,
            10,
            "valuation",
            "valuation_time",
            0,
            label="_dynamic",
            neighbor=True,
            dynamic_deep_threshold=config["dynamic_deep_threshold"],
        )
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate proxy experiments")
    return rows
