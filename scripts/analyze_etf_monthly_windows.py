#!/usr/bin/env python3
"""Summarize every monthly ETF window and verify unchanged latest accounts."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.pool_analysis import validate_window_horizons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("primary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve previous analysis")
    table = pd.read_parquet(args.source / "results.parquet")
    validate_window_horizons(table)
    if not table.status.eq("computed").all() or not table.independent_ledger_verified.all():
        raise ValueError("not all monthly accounts were verified")
    table["years"] = table.window.str.extract(r"rolling_(\d+)y").astype(int)
    summary = table.groupby(["asset", "years", "experiment"], sort=True).agg(
        windows=("annualized_return", "size"),
        worst_annualized_twr=("annualized_return", "min"),
        median_annualized_twr=("annualized_return", "median"),
        worst_drawdown=("max_drawdown", "min"),
        median_wealth_difference=("delta_ending_wealth_vs_pool", "median"),
        worst_wealth_difference=("delta_ending_wealth_vs_pool", "min"),
        best_wealth_difference=("delta_ending_wealth_vs_pool", "max"),
        maximum_capital_shortfall_days=("longest_capital_shortfall_days", "max"),
        maximum_wait_days=("initial_wait_days", "max"),
        median_cash_fraction=("average_cash_fraction", "median"),
    )
    checks = []
    for (asset, years, experiment), rows in table.groupby(["asset", "years", "experiment"]):
        latest = rows.sort_values("end").iloc[-1]
        reference = args.primary / asset / experiment / f"latest_{years}y"
        candidate = args.source / latest.result_directory
        for filename in (
            "daily.parquet",
            "journal.parquet",
            "metrics.json",
            "strategy.json",
            "ledger_audit.json",
        ):
            a, b = sha256_file(reference / filename), sha256_file(candidate / filename)
            zero_serialization_only = False
            if filename == "strategy.json" and a != b:
                old = json.loads((reference / filename).read_text())
                new = json.loads((candidate / filename).read_text())
                changed_types = {key for key in old if type(old[key]) is not type(new[key])}
                zero_serialization_only = (
                    old == new
                    and changed_types == {"core_fraction"}
                    and old["core_fraction"] == new["core_fraction"] == 0
                )
            checks.append(
                {
                    "asset": asset,
                    "years": int(years),
                    "experiment": experiment,
                    "file": filename,
                    "source_sha256": a,
                    "monthly_sha256": b,
                    "exact": a == b,
                    "configuration_zero_serialization_only": zero_serialization_only,
                }
            )
    if not checks or not all(
        x["exact"] or x["configuration_zero_serialization_only"] for x in checks
    ):
        raise AssertionError("monthly latest window differs from primary")
    args.output.mkdir(parents=True)
    table.to_csv(args.output / "all_monthly_accounts.csv", index=False)
    summary.to_csv(args.output / "all_window_summary.csv")
    pd.DataFrame(checks).to_csv(args.output / "latest_equivalence.csv", index=False)
    write_json(
        args.output / "registration.json",
        {
            "source": str(args.source),
            "primary": str(args.primary),
            "source_results_sha256": sha256_file(args.source / "results.parquet"),
            "code": code_revision(),
            "selection": "none",
            "windows": "all_supported_monthly_5y_10y;overlapping_retrospective",
        },
    )
    write_json(
        args.output / "summary.json",
        {
            "accounts": len(table),
            "latest_accounts_exact": len(checks) // 5,
            "financial_payload_files_exact": sum(x["file"] != "strategy.json" for x in checks),
            "all_files_byte_exact": sum(x["exact"] for x in checks),
            "config_zero_serialization_differences": sum(
                x["configuration_zero_serialization_only"] for x in checks
            ),
            "formal_accepted": False,
        },
    )
    write_json(
        args.output / "payloads.json",
        {
            path.name: sha256_file(path)
            for path in sorted(args.output.iterdir())
            if path.name != "registration.json"
        },
    )
    print(summary.to_string())


if __name__ == "__main__":
    main()
