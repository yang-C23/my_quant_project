#!/usr/bin/env python3
"""Compare every registered confirmation horizon and verify unchanged controls."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.pool_analysis import validate_window_horizons, window_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("primary", type=Path)
    parser.add_argument("confirmation", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve previous confirmation analyses")
    for source in (args.primary, args.confirmation):
        if not (source / "summary.json").is_file():
            raise ValueError("complete accounts before comparing confirmation horizons")
    table = pd.read_parquet(args.confirmation / "results.parquet")
    validate_window_horizons(table)
    if not table.status.isin(["computed", "blocked"]).all():
        raise ValueError("unexpected account failure must be investigated")
    computed = table[table.status.eq("computed")].copy()
    if not computed.independent_ledger_verified.all():
        raise ValueError("all accounts require independent ledger verification")

    checks = []
    for row in computed.to_dict("records"):
        experiment = row["experiment"]
        if experiment.startswith("confirmation_20_"):
            counterpart = experiment.replace("confirmation_20_", "pool_", 1)
        elif experiment.startswith("pool_"):
            counterpart = experiment
        else:
            continue
        relative = Path(row["asset"]) / counterpart / row["window"]
        original = args.primary / relative
        current = args.confirmation / row["result_directory"]
        left = json.loads((original / "metrics.json").read_text())
        right = json.loads((current / "metrics.json").read_text())
        changed = sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k))
        changed_payloads = [
            name
            for name in ("daily.parquet", "journal.parquet")
            if sha256_file(original / name) != sha256_file(current / name)
        ]
        if changed or changed_payloads:
            raise ValueError(f"unchanged rule diverged: {relative}: {changed}, {changed_payloads}")
        checks.append(
            {
                "asset": row["asset"],
                "experiment": experiment,
                "primary_experiment": counterpart,
                "window": row["window"],
                "metrics_identical": True,
                "daily_and_journal_bytes_identical": True,
            }
        )
    if not checks:
        raise ValueError("empty equivalence check is not evidence")
    selected = computed[computed.experiment.str.startswith("confirmation_")].copy()
    parsed = selected.experiment.str.extract(
        r"^confirmation_(?P<confirmation_sessions>\d+)_(?P<entry>stabilized|relief)_core(?P<core>[\d.]+)$"
    )
    if parsed.isna().any().any():
        raise ValueError("unexpected confirmation experiment")
    for name in parsed:
        selected[name] = parsed[name]
    selected["confirmation_sessions"] = selected.confirmation_sessions.astype(int)
    keys = ["asset", "entry", "core", "window", "start", "end"]
    metrics = [
        "ending_wealth",
        "annualized_return",
        "max_drawdown",
        "initial_wait_days",
        "longest_capital_shortfall_days",
        "average_cash_fraction",
    ]
    reference = selected[selected.confirmation_sessions.eq(20)][keys + metrics].rename(
        columns={name: f"{name}_20_sessions" for name in metrics}
    )
    paired = selected.merge(reference, on=keys, how="left", validate="many_to_one", indicator=True)
    if not paired["_merge"].eq("both").all():
        raise ValueError("every comparison requires the same account dates and funding")
    paired = paired.drop(columns="_merge")
    for name in metrics:
        paired[f"delta_{name}_vs_20_sessions"] = paired[name] - paired[f"{name}_20_sessions"]

    events_path = args.confirmation / "confirmation_events.parquet"
    events = pd.read_parquet(events_path)
    stages = events[events.stage.isin(["pressure", "stabilized", "relief"])].copy()
    counts = stages.groupby(["asset", "confirmation_window", "stage", "status"]).size()
    args.output.mkdir(parents=True)
    table.to_csv(args.output / "all_accounts.csv", index=False)
    pd.DataFrame(checks).to_csv(args.output / "primary_equivalence.csv", index=False)
    paired.to_csv(args.output / "matched_horizons_all.csv", index=False)
    window_summary(table).to_csv(args.output / "windows_all.csv", index=False)
    counts.rename("events").reset_index().to_csv(args.output / "stage_counts.csv", index=False)
    stages.to_csv(args.output / "all_stage_events.csv", index=False)
    write_json(
        args.output / "registration.json",
        {
            "primary": str(args.primary),
            "confirmation": str(args.confirmation),
            "inputs": {
                str(path): sha256_file(path)
                for path in (
                    args.primary / "registration.json",
                    args.confirmation / "registration.json",
                    args.confirmation / "results.parquet",
                    events_path,
                )
            },
            "code": code_revision(),
            "script_sha256": sha256_file(Path(__file__)),
            "selection": "every_registered_account_and_stage_including_no_entry",
            "interpretation": "posthoc_expiry_sensitivity_not_unseen_validation",
            "formal_accepted": False,
        },
    )
    write_json(
        args.output / "summary.json",
        {
            "accounts": len(table),
            "computed": len(computed),
            "unchanged_primary_equivalents": len(checks),
            "same_date_horizon_pairs": len(paired),
            "stage_rows": len(stages),
            "all_ledgers_verified": True,
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
    print((args.output / "summary.json").read_text())


if __name__ == "__main__":
    main()
