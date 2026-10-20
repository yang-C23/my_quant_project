"""Publication-aware supplemental features with explicit unverified-lag scenarios."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.data.catalog import DataCatalog
from quant.longterm.features import align_available, historical_percentile


def periodic_percentile(
    values: pd.Series, *, years: int, frequency: int, expanding: bool = False
) -> pd.Series:
    """Strictly earlier monthly/weekly observations; no fake daily forward-fill count."""
    if not values.index.is_unique or not values.index.is_monotonic_increasing:
        raise ValueError("unique ordered dates required")
    values = values.where(np.isfinite(values))
    out = pd.Series(np.nan, index=values.index, dtype=float)
    first = values.first_valid_index()
    if first is None:
        return out
    for i, (date, current) in enumerate(values.items()):
        if pd.isna(current) or date < first + pd.DateOffset(years=years):
            continue
        left = 0 if expanding else values.index.searchsorted(date - pd.DateOffset(years=years))
        history = values.iloc[left:i].dropna()
        if len(history) >= frequency * years * 0.8:
            out.iloc[i] = float(
                ((history < current).sum() + 0.5 * (history == current).sum()) / len(history)
            )
    return out


def supplemental_features(
    bars: pd.DataFrame,
    asset: dict,
    catalog: DataCatalog,
    versions: dict,
    config: dict,
    *,
    finra_lag_months: int = 1,
    cftc_lag_days: int = 10,
) -> tuple[pd.DataFrame, list[dict]]:
    """VIX closes and slow leverage proxies are never joined on observation date alone."""
    out = pd.DataFrame(index=bars.index)
    evidence = []
    if asset["market"] != "US":
        return out, evidence
    decisions = (bars.index + pd.Timedelta(hours=16)).tz_localize("America/New_York")

    def align(frame: pd.DataFrame, name: str, age: int) -> pd.Series:
        return pd.Series(
            align_available(frame, decisions, name, maximum_age_days=age).to_numpy(),
            index=bars.index,
        )

    if "cboe_vix" in versions:
        source = catalog.read("cboe_vix", version=versions["cboe_vix"]).copy()
        source["date"] = pd.to_datetime(source.date)
        source = source.sort_values("date")
        source["vix"] = source["close"]
        source["vix_percentile"] = historical_percentile(
            source.set_index("date").vix,
            years=config["supplemental"]["vix_percentile_years"],
        ).to_numpy()
        for name in ("vix", "vix_percentile"):
            out[name] = align(source, name, 7)
        evidence.append(
            {
                "factor": "vix",
                "release_rule": "existing_close_available_17_New_York_after_equity_close",
                "historical_publication_verified": False,
            }
        )
    if "finra_margin" in versions:
        source = catalog.read("finra_margin", version=versions["finra_margin"]).copy()
        source["date"] = pd.to_datetime(source.date)
        source = source.sort_values("date")
        debt = source.margin_debt_usd_million
        source["margin_drawdown_12m"] = debt / debt.rolling(12).max() - 1
        source["margin_change_1m"] = debt.pct_change(fill_method=None)
        source["margin_prior_change_1m"] = source.margin_change_1m.shift(1)
        # This is a labelled sensitivity assumption, never a verified release date.
        source["available_at"] = (
            source.date + pd.offsets.MonthEnd(finra_lag_months) + pd.Timedelta(hours=23, minutes=59)
        ).dt.tz_localize("UTC")
        for name in ("margin_drawdown_12m", "margin_change_1m", "margin_prior_change_1m"):
            out[name] = align(source, name, (finra_lag_months + 2) * 31)
        evidence.append(
            {
                "factor": "margin",
                "release_rule": f"end_of_observation_month_plus_{finra_lag_months}_months",
                "historical_publication_verified": False,
                "scope": "aggregate_US_margin_not_index_specific_forced_liquidation",
            }
        )
    code = {"sp500": "13874A", "nasdaq100": "209742"}.get(asset["id"])
    datasets = sorted(name for name in versions if name.startswith("cftc_tff_futures_"))
    if "cftc_tff_futures_2006_2016" in datasets:
        datasets = [
            name
            for name in datasets
            if name == "cftc_tff_futures_2006_2016" or int(name.rsplit("_", 1)[1]) > 2016
        ]
    if code and datasets:
        source = pd.concat(
            [catalog.read(name, version=versions[name]) for name in datasets], ignore_index=True
        )
        source = source[source.symbol.eq(code)].copy()
        source["date"] = pd.to_datetime(source.date)
        source = source.sort_values("date")
        if source.date.duplicated().any():
            raise ValueError("overlapping CFTC archive observations need revision adjudication")
        fraction = source.leveraged_funds_long / source.open_interest.where(
            source.open_interest > 0
        )
        source["leveraged_long_percentile"] = periodic_percentile(
            pd.Series(fraction.to_numpy(dtype=float), index=source.date),
            years=5,
            frequency=52,
        ).to_numpy()
        source["available_at"] = (
            source.date + pd.Timedelta(days=cftc_lag_days, hours=23, minutes=59)
        ).dt.tz_localize("UTC")
        out["leveraged_long_percentile"] = align(
            source, "leveraged_long_percentile", cftc_lag_days + 14
        )
        evidence.append(
            {
                "factor": "positions",
                "contract_market_code": code,
                "release_rule": f"observation_plus_{cftc_lag_days}_days_assumption",
                "historical_publication_verified": False,
                "pre_2010_observations_are_backfilled_TFF_categories": True,
                "scope": "leveraged_fund_directional_long_contracts_over_OI_excludes_spreading",
            }
        )
    return out, evidence


def shiller_temperature(
    bars: pd.DataFrame,
    observed: pd.DataFrame,
    metric: str,
    window: int | str,
    lag_months: int,
    config: dict,
) -> pd.Series:
    """Monthly revised-value proxy; does not certify original PE or release history."""
    source = observed.copy()
    source["date"] = pd.to_datetime(source.date)
    source = source[source.date >= config["shiller_exploration"]["first_comparable_month"]]
    source = source.sort_values("date").set_index("date", drop=False)
    invert = False
    if metric == "pe":
        values = source.pe_latest_vintage.where(source.pe_latest_vintage > 0)
    elif metric == "cape":
        values = source.cape_latest_vintage.where(source.cape_latest_vintage > 0)
    elif metric == "dividend_yield":
        values, invert = source.dividend_yield_latest_vintage, True
    elif metric == "earnings_yield_spread":
        values = (
            1 / source.pe_latest_vintage.where(source.pe_latest_vintage > 0) - source.bond_yield
        )
        invert = True
    elif metric == "dividend_yield_spread":
        values = source.dividend_yield_latest_vintage - source.bond_yield
        invert = True
    else:
        raise ValueError("Shiller does not provide the requested valuation")
    years = 10 if window == "expanding_10" else int(window)
    rank = periodic_percentile(
        values, years=years, frequency=12, expanding=window == "expanding_10"
    )
    source["temperature"] = 1 - rank if invert else rank
    source["available_at"] = (
        source.date + pd.offsets.MonthEnd(lag_months) + pd.Timedelta(hours=23, minutes=59)
    ).dt.tz_localize("UTC")
    source = source.reset_index(drop=True)
    decisions = (bars.index + pd.Timedelta(hours=16)).tz_localize("America/New_York")
    result = align_available(
        source,
        decisions,
        "temperature",
        maximum_age_days=lag_months * 31 + 35,
    )
    # Expiry belongs to each observation, not the last row of the entire file.
    # A global max(release) would let future appended rows revive stale past signals.
    source["release_epoch_seconds"] = source.available_at.astype("int64") / 1e9
    known_release = align_available(
        source,
        decisions,
        "release_epoch_seconds",
        maximum_age_days=lag_months * 31 + 35,
    )
    age_days = (decisions.asi8 / 1e9 - known_release.to_numpy()) / 86400
    maximum_age = config["shiller_exploration"]["maximum_staleness_after_assumed_release_days"]
    result = result.where(age_days <= maximum_age)
    result.index = bars.index
    return result
