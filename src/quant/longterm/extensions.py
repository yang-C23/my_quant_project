"""Explicit financial proxies; none establish forced selling or actual dealer gamma."""

from __future__ import annotations

import numpy as np
import pandas as pd


def estimated_fund_flow(shares: pd.Series, nav: pd.Series, split_ratio: pd.Series) -> pd.Series:
    """NAV_t*(shares_t - shares_t-1*split_ratio_t); AUM change is not investor flow."""
    if not shares.index.equals(nav.index) or not shares.index.equals(split_ratio.index):
        raise ValueError("aligned observations required")
    return (shares - shares.shift(1) * split_ratio) * nav


def carry_adjusted_basis(
    futures: pd.Series,
    spot: pd.Series,
    days_to_expiry: pd.Series,
    risk_free: pd.Series,
    dividend_yield: pd.Series,
) -> pd.Series:
    """Annualized log basis after continuous carry; no inference at expiry or across rolls."""
    frame = pd.concat([futures, spot, days_to_expiry, risk_free, dividend_yield], axis=1)
    if frame.isna().any().any():
        raise ValueError("matched prices, expiry, rates and dividends are required")
    years = days_to_expiry / 365.2425
    valid = (futures > 0) & (spot > 0) & (years > 0)
    return (np.log(futures / spot) / years - (risk_free - dividend_yield)).where(valid)


def gamma_scenario(
    gamma: pd.Series,
    contracts: pd.Series,
    multiplier: pd.Series,
    spot: pd.Series,
    assumed_dealer_sign: pd.Series,
) -> pd.Series:
    """Dollar delta change per 1% move under supplied, unverified direction assumptions."""
    if not assumed_dealer_sign.isin([-1, 0, 1]).all():
        raise ValueError("dealer direction must be an explicit -1/0/+1 scenario")
    if (gamma < 0).any() or (contracts < 0).any() or (multiplier <= 0).any() or (spot <= 0).any():
        raise ValueError("invalid gamma exposure inputs")
    return gamma * contracts * multiplier * spot**2 * 0.01 * assumed_dealer_sign
