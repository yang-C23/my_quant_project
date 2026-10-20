"""Freeze both vendors and measure how quoted-price discrepancies affect every rule."""

from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

import pandas as pd

from quant.config import Settings, load_config
from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.cash_pool import PoolPolicy, capital_metrics, run_cash_pool
from quant.longterm.diagnostics import verify_price_ledger
from quant.longterm.engine import Strategy, run_strategy
from quant.longterm.ledger import Costs, dec
from quant.longterm.pool_extensions import save_extension_case
from quant.longterm.pool_registry import pool_windows
from quant.longterm.pool_research import _paired_metrics
from quant.longterm.stages import StageSpec, stage_features


def _source_asset(job: tuple[str, str]) -> list[dict]:
    name, directory = job
    root = Path(directory)
    registration = json.loads((root / "registration.json").read_text())
    primary = registration["primary"]
    source_config = registration["config"]
    frames = {
        vendor: pd.read_parquet(root / "inputs" / f"{name}_{vendor}.parquet")
        for vendor in ("tdx", "baostock")
    }
    calendar = frames["tdx"].index
    if not frames["baostock"].index.equals(calendar):
        raise ValueError("source comparison cannot change the funding or observation calendar")
    primary_features = {
        vendor: stage_features(bars, StageSpec(**primary["config"]["stages"]))
        for vendor, bars in frames.items()
    }
    delta = []
    for column in ("pressure", "stabilized", "relief"):
        left, right = primary_features["tdx"][column], primary_features["baostock"][column]
        for date in calendar[left != right]:
            delta.append(
                {
                    "asset": name,
                    "date": str(date.date()),
                    "stage": column,
                    "tdx": bool(left.loc[date]),
                    "baostock": bool(right.loc[date]),
                }
            )
    (root / name).mkdir()
    pd.DataFrame(delta).to_csv(root / name / "stage_differences.csv", index=False)
    warmup = primary["config"]["validation"]["initial_price_warmup"]
    windows = [
        window
        for window in pool_windows(calendar[warmup:], primary["config"])
        if window["id"] == "full"
        or window["id"].startswith(("latest_5y", "latest_10y", "rolling_5y", "rolling_10y"))
    ]
    defaults = primary["config"]["execution"]
    costs = Costs(
        commission_rate=dec(defaults["commission_rate"]),
        minimum_commission=dec(defaults["minimum_commission"]),
        slippage_bps=dec(defaults["slippage_bps"]),
    )
    experiments = {
        experiment["id"]: experiment
        for experiment in primary["experiments"]
        if experiment["id"] in source_config["experiments"]
    }
    if len(experiments) != len(source_config["experiments"]):
        raise ValueError("unregistered source-sensitivity policy")
    records = []
    for vendor, bars in frames.items():
        features = primary_features[vendor]
        controls = {}
        for identifier, experiment in experiments.items():
            policy = PoolPolicy(**experiment["policy"])
            for window in windows:
                kwargs = {
                    "symbol": name,
                    "start": window["start"],
                    "end": window["end"],
                    "costs": costs,
                    "execution": "next_close",
                }
                if experiment["engine"] == "legacy":
                    result = run_strategy(
                        bars,
                        features,
                        Strategy(name=experiment["legacy"], **primary["config"]["funding"]),
                        **kwargs,
                    )
                    result.metrics.update(capital_metrics(result.daily, result.journal))
                else:
                    result = run_cash_pool(bars, features, policy, **kwargs)
                key = (window["id"], policy.core_fraction)
                if key not in controls:
                    controls[key] = run_cash_pool(
                        bars,
                        features,
                        replace(policy, entry="unconditional", exit="none", event_tranches=0),
                        **kwargs,
                    )
                audit = verify_price_ledger(result, bars.close)
                record = {
                    "asset": name,
                    "vendor": vendor,
                    "experiment": identifier,
                    "window": window["id"],
                    "formal_accepted": False,
                    "basis": "price_index_two_source_sensitivity",
                    **_paired_metrics(result, controls[key]),
                }
                path = root / name / vendor / identifier / window["id"]
                records.append(save_extension_case(result, audit, path, record, root))
        write_json(root / name / "progress.json", {"vendor": vendor, "computed": len(records)})
    pd.DataFrame(records).to_parquet(
        root / name / "results.parquet", index=False, compression="zstd"
    )
    return records


def audit_price_sources(
    settings: Settings,
    source: Path,
    destination: Path,
    config_path: Path,
    *,
    replay_run: Path | None = None,
    workers: int = 3,
) -> dict:
    """Check matched real calendars; all prescribed rules and overlapping windows survive."""
    if destination.exists():
        raise ValueError("preserve earlier price-source studies")
    if not 1 <= workers <= 5:
        raise ValueError("use one to five asset workers")
    config = load_config(config_path)
    primary = json.loads((source / "registration.json").read_text())
    catalog = DataCatalog(settings.data_root)
    versions = {
        dataset: catalog.manifest(dataset)["version"] for dataset in config["assets"].values()
    }
    registration = {
        "source": str(source),
        "primary": primary,
        "config": config,
        "source_registration_sha256": sha256_file(source / "registration.json"),
        "versions": versions,
        "code": code_revision(),
        "input_hashes": {
            name: sha256_file(source / "inputs" / f"{name}.parquet") for name in config["assets"]
        },
        "formal_accepted": False,
        "selection": "all_registered_policies",
    }
    if replay_run:
        original = json.loads((replay_run / "registration.json").read_text())
        for key in ("primary", "config", "input_hashes", "source_registration_sha256"):
            if original[key] != registration[key]:
                raise ValueError(f"source replay input mismatch: {key}")
        if original["code"]["sources"] != registration["code"]["sources"]:
            raise ValueError("source replay requires identical implementation bytes")
        registration, versions = original, original["versions"]
    destination.mkdir(parents=True)
    (destination / "inputs").mkdir()
    write_json(destination / "registration.json", registration)
    coverage, differences, jobs, blocked = [], [], [], []
    for name, dataset in config["assets"].items():
        original = pd.read_parquet(source / "inputs" / f"{name}.parquet")
        alternative = catalog.read(dataset, version=versions[dataset])
        alternative.index = pd.to_datetime(alternative.date)
        missing = original.index.difference(alternative.index)
        if len(missing):
            blocked.append(
                {
                    "asset": name,
                    "status": "blocked",
                    "reason": "alternative_dates_missing",
                    "dates": [str(date.date()) for date in missing],
                }
            )
            continue
        alternative = alternative.loc[
            original.index, ["open", "high", "low", "close", "volume", "amount"]
        ]
        for vendor, frame in (("tdx", original), ("baostock", alternative)):
            frame.to_parquet(
                destination / "inputs" / f"{name}_{vendor}.parquet", compression="zstd"
            )
        item = {
            "asset": name,
            "version": versions[dataset],
            "rows": len(original),
            "start": str(original.index[0].date()),
            "end": str(original.index[-1].date()),
        }
        for field in ("open", "high", "low", "close"):
            difference = original[field].astype(float) - alternative[field].astype(float)
            bad = difference.abs().gt(0.0051)
            item[f"{field}_mismatches"] = int(bad.sum())
            for date in original.index[bad]:
                differences.append(
                    {
                        "asset": name,
                        "date": str(date.date()),
                        "field": field,
                        "tdx": float(original.at[date, field]),
                        "baostock": float(alternative.at[date, field]),
                    }
                )
        coverage.append(item)
        jobs.append((name, str(destination)))
    write_json(destination / "coverage.json", coverage)
    write_json(destination / "blocked.json", blocked)
    pd.DataFrame(differences).to_csv(destination / "quote_differences.csv", index=False)
    records = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for rows in pool.map(_source_asset, jobs):
            records.extend(rows)
    table = pd.DataFrame(records)
    table.to_parquet(destination / "results.parquet", index=False, compression="zstd")
    table.to_csv(destination / "results.csv", index=False)
    keys = ["asset", "experiment", "window"]
    control = table[table.vendor.eq("tdx")].set_index(keys)
    comparison = table[table.vendor.eq("baostock")].set_index(keys).copy()
    for column in (
        "annualized_return",
        "max_drawdown",
        "ending_wealth",
        "initial_wait_days",
        "longest_capital_shortfall_days",
        "trades",
    ):
        comparison[f"delta_{column}_vs_tdx"] = comparison[column] - control[column]
    comparison.reset_index().to_csv(destination / "paired_all.csv", index=False)
    summary = {
        "computed": len(table),
        "paired": len(comparison),
        "blocked_assets": len(blocked),
        "all_ledgers_verified": bool(table.independent_ledger_verified.all()),
        "formal_accepted": False,
        "selection": "none",
    }
    write_json(destination / "summary.json", summary)
    payloads = {
        str(p.relative_to(destination)): sha256_file(p)
        for p in sorted(destination.rglob("*"))
        if p.is_file() and p.name not in {"registration.json", "progress.json"}
    }
    write_json(destination / "payloads.json", payloads)
    if replay_run:
        original = json.loads((replay_run / "payloads.json").read_text())
        changed = sorted(
            key for key in set(original) | set(payloads) if original.get(key) != payloads.get(key)
        )
        write_json(
            destination / "replay.json",
            {"identical": not changed, "changed_files": changed, "payloads": len(payloads)},
        )
    return summary
