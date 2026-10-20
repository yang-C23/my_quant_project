#!/usr/bin/env python3
"""Profile frozen real research inputs without changing the registered accounts."""

import argparse
import cProfile
import json
from pathlib import Path
import pstats
import time

import numpy as np
import pandas as pd
import psutil
from threadpoolctl import threadpool_info, threadpool_limits

from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.action_audit import verify_action_ledger
from quant.longterm.asset_inputs import prepare_action_prices
from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.diagnostics import verify_price_ledger
from quant.longterm.features import historical_percentile
from quant.longterm.ledger import Costs, dec
from quant.longterm.research import save_result
from quant.longterm.stages import StageSpec, stage_features


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve prior profiles")
    args.output.mkdir(parents=True)
    registered = json.loads((args.source / "registration.json").read_text())
    config = registered["config"]
    coverage = {
        row["asset"]: row for row in json.loads((args.source / "coverage.json").read_text())
    }
    assets = {row["id"]: row for row in registered["universe"]}
    measurements = []

    def timed(asset, phase, function, *values, **kwargs):
        wall, cpu = time.perf_counter(), time.process_time()
        result = function(*values, **kwargs)
        measurements.append(
            {
                "asset": asset,
                "phase": phase,
                "wall_seconds": time.perf_counter() - wall,
                "cpu_seconds": time.process_time() - cpu,
            }
        )
        return result

    def clean(raw, actions):
        if not raw.index.is_unique or not raw.index.is_monotonic_increasing:
            raise ValueError("invalid dated input")
        if not np.isfinite(raw.close).all() or (raw.close <= 0).any():
            raise ValueError("invalid price")
        if actions is None:
            return raw, raw.copy(), None
        return prepare_action_prices(raw, actions)

    def rolling(bars):
        close = bars.close
        return pd.DataFrame(
            {
                "return5": close.pct_change(5, fill_method=None),
                "vol60": close.pct_change(fill_method=None).shift(5).rolling(60).std(ddof=1),
                "high252": close.rolling(252, min_periods=252).max(),
                "ma10": close.rolling(10).mean(),
            }
        )

    profiler = cProfile.Profile()
    wall_started = time.perf_counter()
    profiler.enable()
    with threadpool_limits(limits=1):
        for name in ("nasdaq100", "csi300", "csi300_etf", "dividend_lowvol"):
            raw = timed(
                name, "read_prices", pd.read_parquet, args.source / "inputs" / f"{name}.parquet"
            )
            path = args.source / "inputs" / f"{name}_actions.parquet"
            actions = timed(name, "read_actions", pd.read_parquet, path) if path.exists() else None
            bars, signals, _ = timed(name, "validate_and_prepare_actions", clean, raw, actions)
            timed(name, "rolling_statistics_microbenchmark", rolling, signals)
            stages = timed(
                name,
                "complete_stage_features",
                stage_features,
                signals,
                StageSpec(**config["stages"]),
            )
            costs = Costs(
                commission_rate=dec(config["execution"]["commission_rate"]),
                minimum_commission=dec(config["execution"]["minimum_commission"]),
                slippage_bps=dec(config["execution"]["slippage_bps"]),
            )
            for core in (0, 0.5):
                case = f"{name}_core{core:g}"
                policy = PoolPolicy(
                    **config["funding"], entry="stabilized", exit="none", core_fraction=core
                )
                result = timed(
                    case,
                    "account_including_decimal",
                    run_cash_pool,
                    bars,
                    stages,
                    policy,
                    symbol=coverage[name].get("symbol", assets[name]["index"]),
                    start=coverage[name]["funding_start_after_shared_warmup"],
                    costs=costs,
                    lot=dec(100 if actions is not None else 0.000001),
                    actions=actions,
                )
                audit = timed(
                    case,
                    "independent_account_audit",
                    verify_price_ledger if actions is None else verify_action_ledger,
                    result,
                    bars.close,
                    *(() if actions is None else (actions, costs)),
                )
                timed(case, "write_result", save_result, result, args.output / case)
                write_json(args.output / case / "ledger_audit.json", audit)
        catalog = DataCatalog(args.data_root)
        for dataset, field in (("cboe_vix", "close"), ("cboe_vxn", "close"), ("cboe_skew", "skew")):
            if dataset not in registered["catalog_versions"]:
                continue
            frame = catalog.read(dataset, version=registered["catalog_versions"][dataset])
            values = pd.Series(
                frame[field].to_numpy(), index=pd.to_datetime(frame.date)
            ).sort_index()
            timed(
                dataset, "five_year_historical_percentiles", historical_percentile, values, years=5
            )
    profiler.disable()
    profiler.dump_stats(str(args.output / "profile.pstats"))
    with (args.output / "profile_top.txt").open("w") as stream:
        pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(65)
    stats = pstats.Stats(profiler).stats
    ledger_methods = [
        {
            "function": key[2],
            "calls": value[1],
            "self_seconds": value[2],
            "inclusive_seconds": value[3],
        }
        for key, value in stats.items()
        if key[0].endswith("longterm/ledger.py")
        and key[2] in {"buy", "sell", "deposit", "settle", "equity", "split", "dividend"}
    ]
    pd.DataFrame(measurements).to_csv(args.output / "phases.csv", index=False)
    write_json(
        args.output / "profile.json",
        {
            "source": str(args.source),
            "source_registration_sha256": sha256_file(args.source / "registration.json"),
            "code": code_revision(),
            "wall_seconds": time.perf_counter() - wall_started,
            "phases": measurements,
            "decimal_ledger_methods": ledger_methods,
            "threadpools": threadpool_info(),
            "memory_rss_bytes": psutil.Process().memory_info().rss,
            "scope": "cProfile_instrumented;rolling_microbenchmark_is_separate_not_additive;"
            "cleaning_is_frozen_research_input_validation_and_company_action_preparation_not_full_TDX_ETL",
        },
    )
    print(pd.DataFrame(measurements).groupby("phase")[["wall_seconds", "cpu_seconds"]].sum())


if __name__ == "__main__":
    main()
