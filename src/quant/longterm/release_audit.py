"""Audit known report interruptions without rewriting the frozen research."""

from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant.config import Settings, load_config
from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, utc_now, write_json
from quant.etl.restart import code_revision
from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.diagnostics import verify_price_ledger
from quant.longterm.ledger import Costs, dec
from quant.longterm.pool_data import supplemental_features
from quant.longterm.pool_extensions import load_study_asset, save_extension_case
from quant.longterm.pool_registry import pool_windows
from quant.longterm.stages import StageSpec, event_study, stage_features


def quarantine_factor(frame: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, pd.Series]:
    """Missing evidence stops dependent entries and active-cycle deployments."""
    output = frame.copy()
    excluded = pd.Series(False, index=frame.index)
    for interval in config["quarantine"]:
        start, end = pd.Timestamp(interval["start"]), pd.Timestamp(interval["end"])
        if end < start:
            raise ValueError("invalid quarantine interval")
        excluded |= (frame.index >= start) & (frame.index <= end)
    output.loc[excluded, config["factor"]] = np.nan
    return output, excluded


def run_release_audit(settings: Settings, source: Path, config_path: Path, output: Path) -> dict:
    """Compare fixed lags, whole-period masks and source-observation release bounds."""
    if output.exists():
        raise ValueError("preserve prior audit output")
    config = load_config(config_path)
    reference = json.loads((source / "registration.json").read_text())
    primary = reference["config"]
    experiments = [
        experiment
        for experiment in reference["experiments"]
        if experiment["id"] in config["experiments"]
    ]
    if len(experiments) != len(config["experiments"]):
        raise ValueError("unknown registered CFTC experiment")
    output.mkdir(parents=True)
    write_json(
        output / "registration.json",
        {
            "registered_at": utc_now(),
            "source": str(source),
            "source_registration_sha256": sha256_file(source / "registration.json"),
            "config": config,
            "config_sha256": sha256_file(config_path),
            "code": code_revision(),
            "selection": "all_six_registered_CFTC_variants_not_performance_selected",
        },
    )
    catalog = DataCatalog(settings.data_root)
    defaults = primary["execution"]
    costs = Costs(
        commission_rate=dec(defaults["commission_rate"]),
        minimum_commission=dec(defaults["minimum_commission"]),
        slippage_bps=dec(defaults["slippage_bps"]),
    )
    coverage = {row["asset"]: row for row in json.loads((source / "coverage.json").read_text())}
    symbols = {row["id"]: row["index"] for row in reference["universe"]}
    records, event_rows = [], []
    for asset in config["assets"]:
        bars, signals, _ = load_study_asset(source, asset)
        source_cache, controls = {}, {}
        for experiment in experiments:
            identifier = experiment["id"]
            lags = experiment.get("supplemental_lags", {})
            key = json.dumps(lags, sort_keys=True)
            if key not in source_cache:
                source_cache[key] = {
                    mode: supplemental_features(
                        bars,
                        {"id": asset, "market": "US"},
                        catalog,
                        reference["catalog_versions"],
                        primary,
                        cftc_publication_bounds=bounds,
                        **lags,
                    )[0]
                    for mode, bounds in (
                        ("registered", None),
                        ("bounded", config["quarantine"]),
                    )
                }
            delay = experiment.get("availability_delay", 0)
            observed = source_cache[key]["registered"].shift(delay)
            bounded = source_cache[key]["bounded"].shift(delay)
            restricted, excluded = quarantine_factor(observed, config)
            original_features = stage_features(
                signals, StageSpec(**experiment["stages"]), supplemental=observed
            )
            masked_features = stage_features(
                signals, StageSpec(**experiment["stages"]), supplemental=restricted
            )
            bounded_features = stage_features(
                signals, StageSpec(**experiment["stages"]), supplemental=bounded
            )
            path = output / "inputs" / asset / identifier
            path.mkdir(parents=True)
            original_features.to_parquet(path / "registered.parquet", compression="zstd")
            masked_features.to_parquet(path / "quarantined.parquet", compression="zstd")
            bounded_features.to_parquet(path / "source_bounded.parquet", compression="zstd")
            policy = PoolPolicy(**experiment["policy"])
            eligible = observed[config["factor"]].notna() & (
                bars.index >= pd.Timestamp(coverage[asset]["funding_start_after_shared_warmup"])
            )
            windows = pool_windows(bars.index[eligible], primary, calendar=bars.index)
            for mode, features in (
                ("registered_assumption", original_features),
                ("quarantine", masked_features),
                ("source_release_bound", bounded_features),
            ):
                events = event_study(
                    signals,
                    features,
                    forward_sessions=tuple(primary["validation"]["event_horizons_sessions"]),
                )
                events = events[events.stage.isin(["pressure", "position_relief"])]
                event_rows.append(events.assign(asset=asset, experiment=identifier, mode=mode))
                for window in windows:
                    if (
                        experiment["scope"] == "neighbor"
                        and window["id"] not in primary["validation"]["neighbor_windows"]
                    ):
                        continue
                    arguments = {
                        "symbol": coverage[asset].get("symbol", symbols[asset]),
                        "start": window["start"],
                        "end": window["end"],
                        "costs": costs,
                    }
                    result = run_cash_pool(bars, features, policy, **arguments)
                    audit = verify_price_ledger(result, bars.close)
                    control_key = (window["start"], window["end"], policy.core_fraction)
                    if control_key not in controls:
                        control_policy = replace(policy, entry="unconditional", exit="none")
                        controls[control_key] = run_cash_pool(
                            bars, original_features, control_policy, **arguments
                        )
                        verify_price_ledger(controls[control_key], bars.close)
                    control = controls[control_key]
                    record = {
                        "asset": asset,
                        "experiment": identifier,
                        "mode": mode,
                        "window": window["id"],
                        "formal_accepted": False,
                        "basis": "price_only_latest_CFTC_vintage",
                        "quarantined_signal_sessions": int(
                            excluded.loc[window["start"] : window["end"]].sum()
                        ),
                        "delta_ending_wealth_vs_pool": result.metrics["ending_wealth"]
                        - control.metrics["ending_wealth"],
                    }
                    case = output / asset / identifier / mode / window["id"]
                    records.append(save_extension_case(result, audit, case, record, output))
            write_json(
                output / "progress.json",
                {"asset": asset, "experiment": identifier, "records": len(records)},
            )
    table = pd.DataFrame(records)
    original = table[table["mode"].eq("registered_assumption")].set_index(
        ["asset", "experiment", "window"]
    )
    pairs = {}
    for mode in ("quarantine", "source_release_bound"):
        paired = table[table["mode"].eq(mode)].set_index(["asset", "experiment", "window"])
        for metric in ("annualized_return", "max_drawdown", "ending_wealth", "initial_wait_days"):
            paired[f"delta_{metric}_vs_registered_assumption"] = paired[metric] - original[metric]
        paired.reset_index().to_csv(output / f"paired_{mode}.csv", index=False)
        pairs[mode] = len(paired)
    table.to_parquet(output / "results.parquet", compression="zstd")
    table.to_csv(output / "results.csv", index=False)
    pd.concat(event_rows, ignore_index=True).to_parquet(
        output / "events.parquet", compression="zstd"
    )
    summary = {
        "directory": str(output),
        "computed": len(table),
        "paired": pairs,
        "all_ledgers_verified": bool(table.independent_ledger_verified.all()),
        "formal_accepted": False,
        "interpretation": (
            "whole_period_quarantine_and_source_bounds_are_distinct_sensitivities;"
            "neither_is_a_complete_historical_release_reconstruction"
        ),
    }
    write_json(output / "summary.json", summary)
    write_json(
        output / "payloads.json",
        {
            str(path.relative_to(output)): sha256_file(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
            and path.name not in {"registration.json", "progress.json", "summary.json"}
        },
    )
    return summary
