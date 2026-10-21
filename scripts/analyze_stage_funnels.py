#!/usr/bin/env python3
"""Count every observable stage, including events rejected by revised valuations."""

from pathlib import Path
import argparse
import json

import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.pool_data import shiller_temperature
from quant.longterm.pool_registry import pool_windows
from quant.longterm.stages import qualify_value_events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("primary", type=Path)
    parser.add_argument("valuation", type=Path)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve previous stage audits")
    primary = json.loads((args.primary / "registration.json").read_text())
    valuation = json.loads((args.valuation / "registration.json").read_text())
    coverage = json.loads((args.primary / "coverage.json").read_text())
    config = primary["config"]
    catalog = DataCatalog(args.data_root)
    source = catalog.read(
        "shiller_monthly", version=valuation["catalog_versions"]["shiller_monthly"]
    )
    summaries, events = [], []
    fingerprints = {}
    for entry in coverage:
        asset = entry["asset"]
        if entry.get("status") == "blocked":
            continue
        path = args.primary / asset / "stages.parquet"
        features = pd.read_parquet(path)
        fingerprints[str(path)] = sha256_file(path)
        first = pd.Timestamp(entry["funding_start_after_shared_warmup"])
        windows = [
            w
            for w in pool_windows(features.index[features.index >= first], config)
            if w["id"] in {"full", "latest_5y", "latest_10y"}
        ]
        temperatures = [("price_only", None)]
        if asset == "sp500":
            for lag in config["shiller_exploration"]["observation_lag_months"]:
                for metric in config["shiller_exploration"]["metrics"]:
                    for years in config["valuation_windows"]:
                        name = f"shiller_{metric}_{years}_lag{lag}"
                        temperatures.append(
                            (
                                name,
                                shiller_temperature(features, source, metric, years, lag, config),
                            )
                        )
        for name, temperature in temperatures:
            sample = (
                features
                if temperature is None
                else qualify_value_events(features.assign(temperature=temperature), 0.4)
            )
            for window in windows:
                part = sample.loc[window["start"] : window["end"]]
                known = (
                    pd.Series(True, index=part.index)
                    if temperature is None
                    else (part.temperature.notna())
                )
                cheap = known if temperature is None else known & part.temperature.lt(0.4)
                qualified = (
                    pd.Series(True, index=part.index)
                    if temperature is None
                    else (part.event_value_eligible)
                )
                row = {
                    "asset": asset,
                    "temperature": name,
                    "window": window["id"],
                    "start": window["start"],
                    "end": window["end"],
                    "sessions": len(part),
                    "known_temperature_sessions": int(known.sum()),
                    "cheap_sessions": int(cheap.sum()) if temperature is not None else None,
                    "stress_sessions": int(part.stress.sum()),
                    "pressure_events": int(part.pressure.sum()),
                    "price_stabilized_events": int(part.stabilized.sum()),
                    "price_relief_events": int(part.relief.sum()),
                    "cheap_pressure_events": int((part.pressure & cheap).sum())
                    if temperature is not None
                    else None,
                    "qualified_stabilized_events": int((part.stabilized & cheap & qualified).sum()),
                    "qualified_relief_events": int((part.relief & cheap & qualified).sum()),
                    "formal_accepted": False,
                }
                summaries.append(row)
            for date, row in sample.loc[first:].iterrows():
                if not (row.pressure or row.stabilized or row.relief):
                    continue
                events.append(
                    {
                        "asset": asset,
                        "temperature": name,
                        "date": str(date.date()),
                        "event_id": int(row.event_id),
                        "pressure": bool(row.pressure),
                        "stabilized": bool(row.stabilized),
                        "relief": bool(row.relief),
                        "drawdown": row.drawdown_252,
                        "five_day_shock_z": row.shock_z,
                        "valuation_percentile": row.get("temperature"),
                        "cheap_at_pressure": row.get("event_value_eligible"),
                        "sessions_since_low": row.sessions_since_event_low,
                        "volatility_fraction": row.volatility_fraction_of_event_peak,
                    }
                )
    args.output.mkdir(parents=True)
    pd.DataFrame(summaries).to_csv(args.output / "stage_counts.csv", index=False)
    pd.DataFrame(events).to_csv(args.output / "every_event_stage.csv", index=False)
    write_json(
        args.output / "registration.json",
        {
            "primary": str(args.primary),
            "valuation": str(args.valuation),
            "primary_registration_sha256": sha256_file(args.primary / "registration.json"),
            "valuation_registration_sha256": sha256_file(args.valuation / "registration.json"),
            "inputs": fingerprints,
            "code": code_revision(),
            "script_sha256": sha256_file(Path(__file__)),
            "interpretation": "descriptive_stage_funnel_not_independent_event_probabilities",
            "formal_accepted": False,
        },
    )
    write_json(
        args.output / "payloads.json",
        {p.name: sha256_file(p) for p in sorted(args.output.glob("*.csv"))},
    )
    print(
        json.dumps({"directory": str(args.output), "rows": len(summaries), "stages": len(events)})
    )


if __name__ == "__main__":
    main()
