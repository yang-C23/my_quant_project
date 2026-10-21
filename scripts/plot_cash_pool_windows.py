#!/usr/bin/env python3
"""Plot every registered annual-step ten-year account, including cash-only failures."""

import argparse
from pathlib import Path

import matplotlib
import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.pool_analysis import validate_window_horizons


def main() -> None:
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        raise ValueError("preserve previous research figures")
    table = pd.read_csv(args.results)
    validate_window_horizons(table)
    policies = {
        "legacy_dca": "Monthly DCA",
        "pool_unconditional_core0": "Unconditional cash pool",
        "pool_stabilized_core0": "Wait for stabilization",
        "pool_stabilized_core0.5": "50% core + wait",
    }
    assets = {"nasdaq100": "Nasdaq 100", "csi300": "CSI 300"}
    selected = table[
        table.status.eq("computed")
        & table.window.fillna("").str.match(r"(?:latest|rolling)_10y")
        & table.experiment.isin(policies)
        & table.asset.isin(assets)
    ].copy()
    if selected.empty:
        raise ValueError("completed ten-year accounts required")
    args.destination.mkdir(parents=True)
    selected.to_csv(args.destination / "plotted_accounts.csv", index=False)
    plt.rcParams["svg.hashsalt"] = "cash-pool-all-ten-year-accounts-v1"
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), layout="constrained")
    for row, (asset, title) in enumerate(assets.items()):
        for policy, label in policies.items():
            group = selected[selected.asset.eq(asset) & selected.experiment.eq(policy)]
            group = group.sort_values("start")
            for column, metric in enumerate(("annualized_return", "max_drawdown")):
                axes[row, column].plot(
                    pd.to_datetime(group.start), group[metric] * 100, label=label, linewidth=1.5
                )
        axes[row, 0].set_title(f"{title}: annualized account TWR")
        axes[row, 1].set_title(f"{title}: maximum account drawdown")
        for ax in axes[row]:
            ax.set_xlabel("Account funding start")
            ax.set_ylabel("%")
            ax.axhline(0, color="black", linewidth=0.6, alpha=0.6)
            ax.grid(alpha=0.2)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(
        "All annual-step 10-year windows — retrospective, overlapping, price-only\n"
        "Same initial/monthly funding; idle cash included; no selection by performance",
        fontsize=11,
    )
    for extension in ("png", "svg"):
        fig.savefig(
            args.destination / f"all_10y_accounts.{extension}",
            dpi=160,
            metadata={"Date": None} if extension == "svg" else {},
        )
    plt.close(fig)
    write_json(
        args.destination / "registration.json",
        {
            "results": str(args.results),
            "results_sha256": sha256_file(args.results),
            "script_sha256": sha256_file(Path(__file__)),
            "code": code_revision(),
            "policies": policies,
            "assets": assets,
            "rows": len(selected),
            "selection": "all_annual_step_ten_year_windows_for_fixed_display_policies",
        },
    )
    write_json(
        args.destination / "payloads.json",
        {
            path.name: sha256_file(path)
            for path in sorted(args.destination.iterdir())
            if path.name != "registration.json"
        },
    )
    print(f"{len(selected)} accounts plotted")


if __name__ == "__main__":
    main()
