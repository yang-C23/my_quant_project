#!/usr/bin/env python3
"""Report all existing US holding/entry/exit windows without choosing winners."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.pool_analysis import validate_window_horizons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/us_holding_review.json"))
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve earlier reviews")
    config = json.loads(args.config.read_text())
    table = pd.read_csv(
        args.analysis / "adjudicated_results.csv", low_memory=False, float_precision="round_trip"
    )
    original_hashes = json.loads((args.source / "payloads.json").read_text())
    selected = []
    coverage = []
    proofs = {}
    for asset in config["assets"]:
        for years in config["horizons_years"]:
            rows = table[
                (table.asset == asset)
                & table.status.eq("computed")
                & table.experiment.isin(config["experiments"])
                & (
                    table.window.str.startswith(f"rolling_{years}y_")
                    | table.window.eq(f"latest_{years}y")
                )
            ].copy()
            coverage.append(
                {
                    "asset": asset,
                    "years": years,
                    "accounts": len(rows),
                    "status": "available" if len(rows) else "insufficient_history",
                }
            )
            if rows.empty:
                continue
            validate_window_horizons(rows)
            if not rows.independent_ledger_verified.eq(True).all():
                raise ValueError("unverified financial account")
            for window, group in rows.groupby("window"):
                if set(group.experiment) != set(config["experiments"]) or len(group) != len(
                    config["experiments"]
                ):
                    raise ValueError(f"unpaired comparison {asset} {window}")
                if group[["start", "end", "contributed"]].nunique().max() != 1:
                    raise ValueError("comparison uses different dates or contributions")
            rows["years"] = years
            for i, row in rows.iterrows():
                directory = args.source / row.result_directory
                for name in (
                    "daily.parquet",
                    "journal.parquet",
                    "metrics.json",
                    "strategy.json",
                    "ledger_audit.json",
                ):
                    p = directory / name
                    relative = str(p.relative_to(args.source))
                    actual = sha256_file(p)
                    if actual != original_hashes[relative]:
                        raise ValueError(f"source payload changed: {relative}")
                    proofs[relative] = actual
                journal = pd.read_parquet(directory / "journal.parquet")
                buys = journal[journal.kind.eq("buy")]
                if len(buys):
                    first = pd.to_datetime(buys.date).min()
                    rows.loc[i, "first_any_buy"] = str(first.date())
                    rows.loc[i, "years_first_buy_to_end"] = (
                        pd.Timestamp(row.end) - first
                    ).days / 365.2425
                else:
                    rows.loc[i, "first_any_buy"] = None
                    rows.loc[i, "years_first_buy_to_end"] = None
            selected.append(rows)
    all_rows = pd.concat(selected, ignore_index=True)
    summary = (
        all_rows.groupby(["asset", "years", "experiment"], sort=True)
        .agg(
            windows=("annualized_return", "size"),
            median_annualized_twr=("annualized_return", "median"),
            worst_annualized_twr=("annualized_return", "min"),
            median_xirr=("xirr", "median"),
            worst_xirr=("xirr", "min"),
            worst_drawdown=("max_drawdown", "min"),
            median_drawdown=("max_drawdown", "median"),
            median_wealth_gap=("delta_ending_wealth_vs_pool", "median"),
            worst_wealth_gap=("delta_ending_wealth_vs_pool", "min"),
            median_cash_fraction=("average_cash_fraction", "median"),
            max_capital_shortfall_days=("longest_capital_shortfall_days", "max"),
            zero_trade_windows=("trades", lambda s: int(s.eq(0).sum())),
            below_contributed_at_end=("ending_profit", lambda s: int(s.lt(0).sum())),
            unrecovered_at_end=("drawdown_unrecovered", lambda s: int(s.eq(True).sum())),
        )
        .reset_index()
    )
    args.output.mkdir(parents=True)
    all_rows.to_csv(args.output / "all_accounts.csv", index=False)
    summary.to_csv(args.output / "summary.csv", index=False)
    all_rows[all_rows.window.str.startswith("latest_")].to_csv(
        args.output / "latest_windows.csv", index=False
    )
    write_json(args.output / "coverage.json", coverage)
    write_json(args.output / "source_payloads_verified.json", proofs)
    write_json(
        args.output / "registration.json",
        {
            "code": code_revision(),
            "script_sha256": sha256_file(Path(__file__)),
            "config": config,
            "analysis_sha256": sha256_file(args.analysis / "adjudicated_results.csv"),
            "source_registration_sha256": sha256_file(args.source / "registration.json"),
            "source_payloads_sha256": sha256_file(args.source / "payloads.json"),
            "source": str(args.source),
            "analysis": str(args.analysis),
        },
    )
    write_json(
        args.output / "payloads.json",
        {
            p.name: sha256_file(p)
            for p in sorted(args.output.iterdir())
            if p.name != "registration.json"
        },
    )
    print(
        json.dumps(
            {
                "accounts": len(all_rows),
                "summary_rows": len(summary),
                "source_files_verified": len(proofs),
                "coverage": coverage,
            }
        )
    )


if __name__ == "__main__":
    main()
