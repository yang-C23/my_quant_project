#!/usr/bin/env python3
"""Compare historical factor-ready windows with complete account calendars."""

from pathlib import Path
import argparse
import json

import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, write_json
from quant.longterm.cash_pool import FACTOR_COLUMNS, PoolPolicy
from quant.longterm.pool_data import shiller_temperature, supplemental_features
from quant.longterm.pool_registry import pool_windows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve earlier audits")
    registration = json.loads((args.source / "registration.json").read_text())
    coverage = json.loads((args.source / "coverage.json").read_text())
    config = registration["config"]
    catalog = DataCatalog(args.data_root)
    values = catalog.read(
        "shiller_monthly", version=registration["catalog_versions"]["shiller_monthly"]
    )
    checked, changed = [], []
    universe = {item["id"]: item for item in registration["universe"]}
    for asset in coverage:
        if asset.get("status") == "blocked":
            continue
        name = asset["asset"]
        bars = pd.read_parquet(args.source / "inputs" / f"{name}.parquet")
        factors = pd.read_parquet(args.source / name / "supplemental.parquet")
        cache, supplemental_cache = {}, {}
        for experiment in registration["experiments"]:
            if experiment.get("assets") and name not in experiment["assets"]:
                continue
            identifier = experiment["id"]
            policy = PoolPolicy(**experiment["policy"])
            if ("kdj" in identifier or policy.entry.endswith("kdj")) and not {
                "high",
                "low",
            }.issubset(bars):
                continue
            if experiment.get("metric") and experiment.get("valuation_source") != "shiller_proxy":
                continue
            eligible = pd.Series(
                bars.index >= pd.Timestamp(asset["funding_start_after_shared_warmup"]),
                index=bars.index,
            )
            lags = experiment.get("supplemental_lags", {})
            if lags:
                lag_key = json.dumps(lags, sort_keys=True)
                if lag_key not in supplemental_cache:
                    supplemental_cache[lag_key] = supplemental_features(
                        bars,
                        universe[name],
                        catalog,
                        registration["catalog_versions"],
                        config,
                        **lags,
                    )[0]
                frame = supplemental_cache[lag_key]
            else:
                frame = factors
            frame = frame.shift(experiment.get("availability_delay", 0))
            columns = FACTOR_COLUMNS.get(policy.event_column, [])
            if not set(columns).issubset(frame):
                continue
            if columns:
                eligible &= frame[columns].notna().all(axis=1)
            if experiment.get("metric"):
                key = (
                    experiment["metric"],
                    experiment["window"],
                    experiment["observation_lag_months"],
                )
                if key not in cache:
                    cache[key] = shiller_temperature(bars, values, *key, config)
                eligible &= cache[key].notna()
            available = bars.index[eligible]
            old = pool_windows(available, config)
            new = pool_windows(available, config, calendar=bars.index)
            if experiment["scope"] == "neighbor":
                permitted = config["validation"]["neighbor_windows"]
                old = [x for x in old if x["id"] in permitted]
                new = [x for x in new if x["id"] in permitted]
            old_by_id, new_by_id = ({x["id"]: x for x in windows} for windows in (old, new))
            for window in sorted(set(old_by_id) | set(new_by_id)):
                before, after = old_by_id.get(window), new_by_id.get(window)
                record = {"asset": name, "experiment": identifier, "window": window}
                checked.append(record)
                if before != after:
                    changed.append(record | {"old": before, "new": after})
        print(name, "calendar checked", flush=True)
    write_json(
        args.output,
        {
            "source": str(args.source),
            "registration_sha256": sha256_file(args.source / "registration.json"),
            "script_sha256": sha256_file(Path(__file__)),
            "checked_windows": len(checked),
            "changed_windows": changed,
            "unchanged": not changed,
        },
    )


if __name__ == "__main__":
    main()
