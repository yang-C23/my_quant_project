"""Causal, individually observable stages of a stress/recovery investment event."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from quant.longterm.features import price_features


@dataclass(frozen=True)
class StageSpec:
    """Small prespecified neighborhood; volatility before the five-day shock."""

    drawdown: float = 0.20
    sigma: float = 2.0
    confirmation: int = 5
    event_window: int = 20
    quiet_sessions: int = 20
    relief_fraction: float = 0.80
    volatility_lag: int = 5
    vix_high_percentile: float = 0.90
    vix_relief_fraction: float = 0.80
    version: str = "stages-v1-close-only"

    def __post_init__(self) -> None:
        if not (0 < self.drawdown < 1 and self.sigma > 0):
            raise ValueError("invalid stress thresholds")
        if min(self.confirmation, self.event_window, self.quiet_sessions, self.volatility_lag) < 1:
            raise ValueError("stage windows must be positive")
        if not (0 < self.relief_fraction < 1 and 0 < self.vix_relief_fraction < 1):
            raise ValueError("relief requires a fraction below one")


def stage_features(
    bars: pd.DataFrame,
    spec: StageSpec = StageSpec(),
    *,
    supplemental: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Measure stages at the close; the engine alone applies the t+1 execution.

    Supplemental observations MUST already be aligned by their availability
    timestamps. Missing observations remain missing; they never mean low risk.
    Close-only stabilization is identical across markets, including US references.
    """
    if not bars.index.is_monotonic_increasing or not bars.index.is_unique:
        raise ValueError("unique increasing observations required")
    close = bars["close"].astype(float)
    if not np.isfinite(close).all() or (close <= 0).any():
        raise ValueError("invalid stage prices")
    returns = close.pct_change(fill_method=None)
    out = pd.DataFrame(index=bars.index)
    out["close"] = close
    out["high_252"] = close.rolling(252, min_periods=252).max()
    out["drawdown_252"] = close / out["high_252"] - 1
    out["return_5"] = close.pct_change(5, fill_method=None)
    out["pre_shock_volatility"] = returns.shift(spec.volatility_lag).rolling(60).std(ddof=1)
    out["realized_volatility_5"] = returns.rolling(5).std(ddof=1)
    out["shock_z"] = out["return_5"] / (out["pre_shock_volatility"] * np.sqrt(5))
    out["stress"] = (
        (out["drawdown_252"] <= -spec.drawdown)
        & (out["shock_z"] <= -spec.sigma)
        & (out["pre_shock_volatility"] > 0)
    )
    out["sma_10"] = close.rolling(10).mean()
    # KDJ is retained only when true high and low observations exist.
    out["j"] = price_features(bars)["j"]
    if supplemental is not None:
        if not supplemental.index.equals(bars.index):
            raise ValueError("supplemental observations must already use the signal calendar")
        if set(supplemental) & set(out):
            raise ValueError("supplemental columns cannot replace price features")
        out = pd.concat([out, supplemental], axis=1)
    for name in (
        "pressure",
        "stabilized",
        "relief",
        "vix_relief",
        "margin_relief",
        "position_relief",
    ):
        out[name] = False
    out["event_id"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out["event_anchor"] = np.nan
    out["event_age"] = np.nan
    out["sessions_since_event_low"] = np.nan
    out["volatility_fraction_of_event_peak"] = np.nan
    data = out.to_dict("records")
    last_stress, event, start, last_low = -spec.quiet_sessions, 0, None, None
    low, anchor, peak_vol, peak_vix = np.nan, np.nan, np.nan, np.nan
    seen, vix_was_high = set(), False
    for i, row in enumerate(data):
        if row["stress"] and i - last_stress >= spec.quiet_sessions:
            event += 1
            start, last_low, low = i, i, row["close"]
            anchor, peak_vol = row["high_252"], row["realized_volatility_5"]
            peak_vix = row.get("vix", np.nan)
            vix_was_high = row.get("vix_percentile", np.nan) >= spec.vix_high_percentile
            seen = set()
            row["pressure"] = True
        if row["stress"]:
            last_stress = i
        if start is None or i - start > spec.event_window:
            start = None
            continue
        row["event_id"], row["event_anchor"], row["event_age"] = event, anchor, i - start
        if row["close"] < low:
            low, last_low = row["close"], i
        peak_vol = max(peak_vol, row["realized_volatility_5"])
        if pd.notna(row.get("vix")):
            peak_vix = max(peak_vix, row["vix"]) if pd.notna(peak_vix) else row["vix"]
        vix_was_high |= row.get("vix_percentile", np.nan) >= spec.vix_high_percentile
        row["sessions_since_event_low"] = i - last_low
        ratio = row["realized_volatility_5"] / peak_vol if peak_vol > 0 else np.nan
        row["volatility_fraction_of_event_peak"] = ratio
        stabilized = i - last_low >= spec.confirmation and row["close"] > row["sma_10"]
        conditions = {
            "stabilized": stabilized,
            "relief": stabilized and ratio <= spec.relief_fraction,
            "vix_relief": (
                stabilized
                and vix_was_high
                and peak_vix > 0
                and row.get("vix", np.nan) / peak_vix <= spec.vix_relief_fraction
            ),
            "margin_relief": (
                stabilized
                and row.get("margin_drawdown_12m", np.nan) <= -0.10
                and row.get("margin_change_1m", np.nan) >= row.get("margin_prior_change_1m", np.nan)
            ),
            "position_relief": (stabilized and row.get("leveraged_long_percentile", np.nan) < 0.40),
        }
        for name, passed in conditions.items():
            if passed and name not in seen:
                row[name] = True
                seen.add(name)
    result = pd.DataFrame(data, index=out.index)
    result["event_id"] = result["event_id"].astype("Int64")
    result.attrs["spec"] = asdict(spec)
    return result


def event_study(
    bars: pd.DataFrame,
    stages: pd.DataFrame,
    *,
    forward_sessions: tuple[int, ...] = (20, 60, 252, 1260, 2520),
) -> pd.DataFrame:
    """Retain every stress event and each absent/censored confirmation.

    Entry is the following observed session. Return and MAE labels use future
    prices only here, never in a signal. Waiting alternatives share the event
    identification date and include the rebound already missed before entry.
    """
    if not bars.index.equals(stages.index):
        raise ValueError("event features must share the price calendar")
    prices = bars["close"].to_numpy(dtype=float)
    dates = bars.index
    requirements = {
        "vix_relief": ("vix", "vix_percentile"),
        "margin_relief": ("margin_drawdown_12m", "margin_change_1m", "margin_prior_change_1m"),
        "position_relief": ("leveraged_long_percentile",),
    }
    window = stages.attrs["spec"]["event_window"]
    rows = []
    for event_start in np.flatnonzero(stages["pressure"]):
        event_id = int(stages.iloc[event_start]["event_id"])
        cluster = stages[stages.event_id.eq(event_id).fillna(False)]
        reference_entry = event_start + 1
        for name in (
            "pressure",
            "stabilized",
            "relief",
            "vix_relief",
            "margin_relief",
            "position_relief",
        ):
            triggers = cluster.index[cluster[name]]
            signal_date = triggers[0] if len(triggers) else None
            index = dates.get_loc(signal_date) + 1 if signal_date is not None else None
            known = cluster.loc[[signal_date]] if signal_date is not None else cluster
            evidence = all(
                column in known and known[column].notna().all()
                for column in requirements.get(name, ())
            )
            complete_window = event_start + window < len(dates)
            tradable = evidence and index is not None and index < len(dates)
            status = (
                "entered"
                if tradable
                else (
                    "factor_unavailable"
                    if not evidence
                    else "signal_at_sample_end"
                    if index is not None
                    else "no_confirmation_in_window"
                    if complete_window
                    else "confirmation_window_censored"
                )
            )
            row = {
                "event_id": event_id,
                "event_date": str(dates[event_start].date()),
                "stage": name,
                "signal_date": str(signal_date.date()) if signal_date is not None else None,
                "entry_date": str(dates[index].date()) if tradable else None,
                "status": status,
                "drawdown_at_event": float(stages.iloc[event_start]["drawdown_252"]),
                "shock_z": float(stages.iloc[event_start]["shock_z"]),
                "wait_sessions": index - reference_entry if tradable else None,
                "entry_price_vs_immediate": prices[index] / prices[reference_entry] - 1
                if tradable and reference_entry < len(dates)
                else None,
            }
            for horizon in forward_sessions:
                # Exact trading-session horizons; never shrink an incomplete future window.
                complete = tradable and index + horizon < len(prices)
                row[f"forward_return_{horizon}"] = (
                    prices[index + horizon] / prices[index] - 1 if complete else None
                )
                row[f"mae_{horizon}"] = (
                    prices[index : index + horizon + 1].min() / prices[index] - 1
                    if complete
                    else None
                )
                common_end = reference_entry + horizon
                common_complete = common_end < len(prices)
                row[f"event_horizon_return_{horizon}"] = (
                    prices[common_end] / prices[index] - 1
                    if tradable and index <= common_end and common_complete
                    else 0.0
                    if common_complete and index is None and evidence and complete_window
                    else None
                )
                row[f"future_censored_{horizon}"] = not complete
            rows.append(row)
    return pd.DataFrame(rows)


def qualify_value_events(stages: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Pressure must occur while cheap; later entry independently rechecks valuation."""
    if not {"temperature", "event_id", "pressure"}.issubset(stages):
        raise ValueError("event identity, pressure and explicit valuation required")
    cheap = stages.temperature.notna() & stages.temperature.lt(threshold)
    qualifying = stages.loc[stages.pressure & cheap, "event_id"].dropna()
    out = stages.copy()
    out["event_value_eligible"] = out.event_id.isin(qualifying)
    return out
