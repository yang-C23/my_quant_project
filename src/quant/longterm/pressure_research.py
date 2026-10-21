"""Prespecified incremental tests of first-party pressure proxies, with missing cases."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.snapshots import write_json
from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.derivative_features import (
    factor_confirmation,
    futures_basis_features,
    options_activity_features,
)
from quant.longterm.diagnostics import verify_price_ledger
from quant.longterm.features import historical_percentile
from quant.longterm.ledger import Costs
from quant.longterm.pool_analysis import clustered_event_comparisons
from quant.longterm.pool_extensions import _failed_case, load_study_asset, save_extension_case
from quant.longterm.pool_registry import pool_windows
from quant.longterm.stages import StageSpec, event_study, stage_features


def lag_observations(
    frame: pd.DataFrame, calendar: pd.DatetimeIndex, lag: int, ttl: int
) -> pd.DataFrame:
    """Explicit exploratory publication lag; not a fabricated historical release timestamp.

    A value observed at a session close first enters the signal after `lag`
    subsequent target-market sessions; the account executes another session later.
    Old observations may only carry forward within the bounded calendar-day TTL.
    """
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing or lag < 1:
        raise ValueError("unique sorted factor observations and positive lag required")
    union = frame.index.union(calendar).sort_values()
    # Forward the whole last observation, never individual fields across a missing
    # latest observation. A newly missing field must remain unavailable.
    positions = pd.Series(np.arange(len(frame)), index=frame.index).reindex(union).ffill()
    positions = positions.reindex(calendar).shift(lag)
    result = pd.DataFrame(np.nan, index=calendar, columns=frame.columns)
    known = positions.notna()
    chosen = positions.loc[known].astype(int).to_numpy()
    result.loc[known] = frame.iloc[chosen].to_numpy()
    dates = pd.Series(pd.NaT, index=calendar)
    dates.loc[known] = frame.index[chosen].to_numpy()
    fresh = (pd.Series(calendar, index=calendar) - dates).dt.days.between(0, ttl)
    return result.where(fresh, axis=0)


def pressure_inputs(
    source: Path, catalog: DataCatalog, versions: dict, config: dict
) -> list[tuple[str, str, pd.DataFrame, dict]]:
    """Build raw dated factor histories before evaluating any portfolio returns."""
    output = []
    settings = config["additional_pressure"]

    def read(name: str) -> pd.DataFrame:
        data = catalog.read(name, version=versions[name])
        data["date"] = pd.to_datetime(data.date)
        return data.set_index("date").sort_index()

    jobs = [
        (asset, name, "close", "vxn") for asset, name in settings["us_volatility_index"].items()
    ]
    jobs += [(asset, "cboe_skew", "skew", "skew") for asset in settings["skew_assets"]]
    jobs += [
        (asset, "cboe_total_putcall", "put_call_ratio", "putcall")
        for asset in settings["total_putcall_assets"]
    ]
    for asset, dataset, column, factor in jobs:
        if dataset not in versions:
            output.append((asset, factor, pd.DataFrame(), {"reason": "source_missing"}))
            continue
        raw = read(dataset)[[column]].rename(columns={column: "value"})
        # The 2012 reporting regime change is not silently mixed into one rank.
        if factor == "putcall":
            rank = pd.Series(np.nan, index=raw.index)
            for part in (raw.loc[:"2012-05-31"], raw.loc["2012-06-01":]):
                rank.loc[part.index] = historical_percentile(
                    part.value, years=settings["index_percentile_years"]
                )
        else:
            rank = historical_percentile(raw.value, years=settings["index_percentile_years"])
        raw["rank"] = rank
        raw["extreme"] = rank.ge(settings["high_percentile"]).astype(float).where(rank.notna())
        raw["relieved"] = rank.le(settings["relieved_percentile"]).astype(float).where(rank.notna())
        raw["evidence"] = rank
        output.append((asset, factor, raw, {"dataset": dataset, "version": versions[dataset]}))
    if "sse_margin_daily" in versions:
        raw = read("sse_margin_daily")
        balance = raw.financing_balance_cny
        drawdown = balance / balance.rolling(settings["margin_peak_window"]).max() - 1
        change = balance.pct_change(settings["margin_change_sessions"], fill_method=None)
        available = drawdown.notna() & change.notna() & change.shift(1).notna()
        frame = pd.DataFrame(
            {
                "value": balance,
                "drawdown": drawdown,
                "change": change,
                "extreme": drawdown.le(settings["margin_drawdown"]).astype(float).where(available),
                "relieved": change.ge(change.shift(1)).astype(float).where(available),
                "evidence": drawdown.where(available),
            }
        )
        for asset in settings["shanghai_margin_assets"]:
            output.append(
                (
                    asset,
                    "sse_financing",
                    frame,
                    {
                        "dataset": "sse_margin_daily",
                        "scope": "Shanghai_aggregate_not_index_specific",
                    },
                )
            )
    archives = [
        catalog.read(name, version=version)
        for name, version in sorted(versions.items())
        if name.startswith("cffex_")
    ]
    if not archives:
        return output
    contracts = pd.concat(archives, ignore_index=True)
    if contracts.duplicated(["date", "symbol"]).any():
        raise ValueError("overlapping CFFEX archives require adjudication")
    calendar = load_study_asset(source, "csi300")[0].index
    for asset, prefix in config["derivatives"]["assets"].items():
        bars = load_study_asset(source, asset)[0]
        raw, audit = futures_basis_features(
            contracts, bars.close, prefix, config["derivatives"]["basis"], expiry_calendar=calendar
        )
        if "basis_percentile" in raw:
            rank = raw.basis_percentile
            rule = config["derivatives"]["basis"]
            raw["extreme"] = (
                (rank.le(rule["stress_percentile"]) & raw.basis_30d.lt(0))
                .astype(float)
                .where(rank.notna())
            )
            raw["relieved"] = rank.ge(rule["relief_percentile"]).astype(float).where(rank.notna())
            raw["evidence"] = rank
        output.append((asset, "seasonal_basis", raw.select_dtypes(include="number"), audit))
    for asset, prefix in config["derivatives"]["options"].items():
        bars = load_study_asset(source, asset)[0]
        raw, audit = options_activity_features(
            contracts,
            bars.close,
            prefix,
            config["derivatives"]["options_activity"],
            expiry_calendar=calendar,
        )
        if "deep_put_percentile" in raw:
            rank = raw.deep_put_percentile
            raw["extreme"] = rank.ge(0.9).astype(float).where(rank.notna())
            raw["relieved"] = rank.le(0.7).astype(float).where(rank.notna())
            raw["evidence"] = rank
        output.append((asset, "deep_put_activity", raw.select_dtypes(include="number"), audit))
    return output


def run_pressure_cases(
    source: Path,
    root: Path,
    config: dict,
    primary: dict,
    catalog: DataCatalog,
    versions: dict,
    costs: Costs,
) -> list[dict]:
    """Paired controls share funding dates, initial cash and long-term core fractions."""
    rows, all_events, audits = [], [], []
    inputs = pressure_inputs(source, catalog, versions, config)
    for asset, factor, raw, audit in inputs:
        if "evidence" not in raw or raw.evidence.notna().sum() < 60:
            rows.append(
                {
                    "group": "pressure",
                    "asset": asset,
                    "experiment": factor,
                    "status": "blocked",
                    "reason": "insufficient_factor_history",
                }
            )
            audits.append({"asset": asset, "factor": factor, **audit})
            continue
        bars, signals, _ = load_study_asset(source, asset)
        base = stage_features(signals, StageSpec(**primary["stages"]))
        directory = root / "pressure_inputs" / asset / factor
        directory.mkdir(parents=True)
        raw.to_parquet(directory / "observations.parquet", compression="zstd")
        derivative = factor in {"seasonal_basis", "deep_put_activity"}
        lags = (
            config["derivatives"]["publication_lag_sessions"]
            if derivative
            else (config["additional_pressure"]["observation_lag_sessions"])
        )
        for lag in lags:
            aligned = lag_observations(
                raw, bars.index, lag, config["additional_pressure"]["ttl_calendar_days"]
            )
            features = base.copy()
            features["external_evidence"] = aligned.evidence
            features["external_event"] = factor_confirmation(
                features,
                aligned.extreme.eq(1),
                aligned.relieved.eq(1),
                aligned.evidence.notna(),
                confirmation=primary["stages"]["confirmation"],
            )
            features.to_parquet(directory / f"features_lag{lag}.parquet", compression="zstd")
            known = aligned.evidence.notna()
            valid = bars.index[
                known & (bars.index >= bars.index[primary["validation"]["initial_price_warmup"]])
            ]
            evidence = {
                "asset": asset,
                "factor": factor,
                "lag_sessions": lag,
                **audit,
                "valid_dates": int(known.sum()),
                "confirmations": int(features.external_event.sum()),
                "available_from": str(valid[0].date()) if len(valid) else None,
                "available_to": str(valid[-1].date()) if len(valid) else None,
                "publication": "assumed_lag_not_verified_historical_release",
            }
            audits.append(evidence)
            events = event_study(
                signals,
                features,
                forward_sessions=tuple(config["event_analysis"]["horizons"]),
                additional_stages={"external_event": ("external_evidence",)},
            )
            if not events.empty:
                events = events[events.stage.isin(["pressure", "external_event"])].copy()
                # Each factor/lag needs its own immediate-entry comparator.
                events["asset"] = f"{asset}__{factor}__lag{lag}"
                events["stage"] = events.stage.replace({"external_event": factor})
                all_events.append(events)
            for window in pool_windows(valid, primary, calendar=bars.index):
                for core in (0, 0.5):
                    for entry in ("external_event", "unconditional", "pressure", "stabilized"):
                        identifier = f"{factor}_lag{lag}_{entry}_core{core:g}"
                        path = root / "pressure" / asset / identifier / window["id"]
                        record = {
                            "group": "pressure",
                            "asset": asset,
                            "experiment": identifier,
                            "factor": factor,
                            "lag_sessions": lag,
                            "entry": entry,
                            "core": core,
                            "window": window["id"],
                            "formal_accepted": False,
                            "basis": "price_index_proxy_not_ETF_total_return",
                        }
                        try:
                            result = run_cash_pool(
                                bars,
                                features,
                                PoolPolicy(
                                    **primary["funding"],
                                    entry=entry,
                                    exit="none",
                                    core_fraction=core,
                                ),
                                symbol=asset,
                                start=window["start"],
                                end=window["end"],
                                costs=costs,
                            )
                            ledger_audit = verify_price_ledger(result, bars.close)
                            rows.append(
                                save_extension_case(result, ledger_audit, path, record, root)
                            )
                        except Exception as exc:
                            rows.append(_failed_case(path, record, exc))
            write_json(
                root / "progress.json",
                {"factor": factor, "asset": asset, "lag": lag, "pressure_records": len(rows)},
            )
    write_json(root / "pressure_coverage.json", audits)
    if all_events:
        events = pd.concat(all_events, ignore_index=True)
        events.to_parquet(root / "pressure_events.parquet", compression="zstd")
        summary, leave_out = clustered_event_comparisons(events, config["event_analysis"])
        summary.to_csv(root / "pressure_event_clusters.csv", index=False)
        leave_out.to_csv(root / "pressure_leave_one_crisis_out.csv", index=False)
    for name, reason in {
        "dealer_net_gamma": "dealer_direction_position_inventory_missing",
        "US_intraday_0DTE": "free_verified_historical_quote_chain_and_trade_direction_missing",
        "deep_OTM_price_surge": "synchronized_bid_ask_and_quote_quality_missing",
        "fully_carry_adjusted_basis": "point_in_time_expected_dividends_missing",
    }.items():
        rows.append(
            {
                "group": "pressure",
                "asset": "unverified",
                "experiment": name,
                "status": "blocked",
                "reason": reason,
            }
        )
    return rows
