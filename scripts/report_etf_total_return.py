#!/usr/bin/env python3
"""All-cohort, paired and era analyses from frozen ETF/cash experiments."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from report_entry_horizons import paired_tables


KEYS = ["asset", "rule", "origin", "years", "variant"]


def checked_csv(root: Path, name: str) -> pd.DataFrame:
    expected = json.loads((root / "payloads.json").read_text())[name]
    if sha256_file(root / name) != expected:
        raise ValueError(f"changed research payload: {root / name}")
    return pd.read_csv(root / name)


def summarize(table: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    rows = []
    for key, frame in table.groupby(groups, dropna=False, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(groups, key, strict=True))
        full = frame[frame.status.eq("complete")]
        row.update(
            cohorts=len(frame),
            complete=len(full),
            unique_entries=full.entry.nunique(),
            censored=int(frame.status.eq("right_censored").sum()),
            no_entry=int(frame.status.eq("no_entry").sum()),
        )
        if len(full):
            row.update(
                terminal_losses=int(full.ending_principal_loss.sum()),
                longest_principal_shortfall_days=int(full.longest_capital_shortfall_days.max()),
                peak_recovery_censored=int(full.post_peak_recovery_censored.sum()),
                median_wait_days=float(full.wait_days.median()),
                max_wait_days=int(full.wait_days.max()),
            )
            for name in (
                "post_annualized_return",
                "annualized_return",
                "post_xirr",
                "post_max_drawdown",
                "post_maximum_principal_loss",
                "average_cash_fraction",
                "ending_wealth",
                "gross_dividends",
                "wealth_gap_vs_origin_pool",
            ):
                row["median_" + name] = float(full[name].median())
                row["min_" + name] = float(full[name].min())
                row["max_" + name] = float(full[name].max())
            row["entry_balanced_median_ann"] = float(
                full.groupby("entry").post_annualized_return.median().median()
            )
        rows.append(row)
    return pd.DataFrame(rows)


def report(root: Path, target: Path, cash: Path, diagnostics: list[Path], old_price: Path) -> dict:
    if target.exists():
        raise ValueError("new report destination required")
    target.mkdir(parents=True)
    table = checked_csv(root, "all_cohort_results.csv")
    groups = ["asset", "rule", "variant", "years"]
    summary = summarize(table, groups)
    summary.to_csv(target / "all_summaries.csv", index=False)
    full = table[table.status.eq("complete")]
    paired, effects = paired_tables(table)
    paired.to_csv(target / "exit_paired_rows.csv", index=False)
    effects.to_csv(target / "exit_paired_effects.csv", index=False)
    hold = full[full.variant.eq("entry_pool_hold")].merge(
        full[full.variant.eq("origin_pool_hold")],
        on=["asset", "rule", "origin", "entry", "years", "end"],
        suffixes=("", "_origin"),
        validate="one_to_one",
    )
    if not hold.contributed.eq(hold.contributed_origin).all():
        raise ValueError("entry comparison funding differs")
    for metric in ("ending_wealth", "max_loss_vs_contributions", "max_drawdown"):
        hold[metric + "_delta"] = hold[metric] - hold[metric + "_origin"]
    hold.to_csv(target / "entry_paired_rows.csv", index=False)
    rows = []
    for key, frame in hold.groupby(["asset", "rule", "years"]):
        row = dict(zip(["asset", "rule", "years"], key, strict=True))
        row.update(
            pairs=len(frame),
            unique_entries=frame.entry.nunique(),
            wealth_improved=int(frame.ending_wealth_delta.gt(0.01).sum()),
            principal_risk_reduced=int(frame.max_loss_vs_contributions_delta.gt(1e-12).sum()),
            median_wait_days=float(frame.wait_days.median()),
            median_wealth_delta=float(frame.ending_wealth_delta.median()),
            median_principal_risk_delta=float(frame.max_loss_vs_contributions_delta.median()),
        )
        rows.append(row)
    pd.DataFrame(rows).to_csv(target / "entry_paired_effects.csv", index=False)
    eras = []
    for axis in ("origin", "entry"):
        for year in (1993, 2000, 2010):
            part = table[table[axis].ge(f"{year}-01-01")]
            eras.append(summarize(part, groups).assign(era_axis=axis, from_year=year))
    pd.concat(eras).to_csv(target / "era_summaries.csv", index=False)
    # The older price-only series is a stress comparison, never spliced into an ETF.
    price = checked_csv(old_price, "all_cohort_results.csv")
    price = price[price.asset.isin(["sp500", "nasdaq100"]) & price.rule.eq("unconditional")]
    price_eras = []
    for year in (1975, 1993, 2000, 2010):
        price_eras.append(
            summarize(price[price.origin.ge(f"{year}-01-01")], groups).assign(from_year=year)
        )
    pd.concat(price_eras).to_csv(target / "price_only_era_diagnostic.csv", index=False)
    # Preserve every tied worst case of each variant; do not hide losing strategies.
    worst = []
    for _, frame in full.groupby(groups):
        for name in ("post_annualized_return", "post_max_drawdown", "post_maximum_principal_loss"):
            worst.append(frame[frame[name].eq(frame[name].min())].assign(worst_by=name))
    pd.concat(worst).to_csv(target / "all_worst_cases.csv", index=False)
    temperature_file = "inputs/sp500_archive_temperature.parquet"
    hashes = json.loads((root / "payloads.json").read_text())
    if sha256_file(root / temperature_file) != hashes[temperature_file]:
        raise ValueError("valuation input checksum changed")
    temperature = pd.read_parquet(root / temperature_file)
    valuation = []
    for year, frame in temperature.groupby(temperature.index.year):
        usable = frame[frame.temperature.notna()]
        valuation.append(
            dict(
                year=year,
                sessions=len(frame),
                available=len(usable),
                below40=int(usable.temperature.lt(0.4).sum()),
                above80=int(usable.temperature.ge(0.8).sum()),
                vintages=usable.vintage.nunique(),
            )
        )
    pd.DataFrame(valuation).to_csv(target / "valuation_coverage.csv", index=False)
    sensitivity = []
    for diagnostic in diagnostics:
        alt = checked_csv(diagnostic, "all_cohort_results.csv")
        summarize(alt, groups).to_csv(target / f"{diagnostic.name}_summaries.csv", index=False)
        joint = table.merge(alt, on=KEYS, suffixes=("", "_alternative"), validate="one_to_one")
        for name in ("entry", "end", "status"):
            joint[name + "_changed"] = joint[name].fillna("") != joint[
                name + "_alternative"
            ].fillna("")
        joint["wealth_delta"] = joint.ending_wealth_alternative - joint.ending_wealth
        joint["ann_delta"] = joint.post_annualized_return_alternative - joint.post_annualized_return
        joint.to_csv(target / f"{diagnostic.name}_all_pairs.csv", index=False)
        sensitivity.append(
            dict(
                run=diagnostic.name,
                pairs=len(joint),
                entry_changed=int(joint.entry_changed.sum()),
                end_changed=int(joint.end_changed.sum()),
                status_changed=int(joint.status_changed.sum()),
                max_absolute_wealth_delta=float(joint.wealth_delta.abs().max()),
                max_absolute_ann_delta=float(joint.ann_delta.abs().max()),
            )
        )
    write_json(target / "diagnostics.json", sensitivity)
    wait = checked_csv(cash, "all_waiting_results.csv")
    wait_rows = []
    for key, frame in wait.groupby(["asset", "rule", "period"]):
        observed = frame[frame.status.eq("complete") & frame.still_waiting.eq(True)]
        row = dict(zip(["asset", "rule", "period"], key, strict=True))
        row.update(
            comparisons=len(frame),
            complete_still_waiting=len(observed),
            positive_cash_gain=int(observed.gain_vs_zero_cash.gt(0).sum()),
            beats_stock_pool=int(observed.gap_vs_stock_pool.gt(0).sum()),
        )
        for name in (
            "gain_vs_zero_cash",
            "gap_vs_stock_pool",
            "bil_annualized",
            "bil_max_drawdown",
        ):
            row["median_" + name] = float(observed[name].median())
            row["min_" + name] = float(observed[name].min())
            row["max_" + name] = float(observed[name].max())
        wait_rows.append(row)
    pd.DataFrame(wait_rows).to_csv(target / "cash_wait_summaries.csv", index=False)
    make_plot(summary, target)
    receipt = dict(
        source=str(root),
        cash=str(cash),
        diagnostics=[str(p) for p in diagnostics],
        source_payloads_sha256=sha256_file(root / "payloads.json"),
        reporter_sha256=sha256_file(Path(__file__)),
        comparison_rows=len(table),
        formal_accepted=False,
        selection="all_registered_rows_and_failures; overlapping_not_independent",
    )
    write_json(target / "receipt.json", receipt)
    write_json(
        target / "payloads.json",
        {p.name: sha256_file(p) for p in sorted(target.iterdir()) if p.is_file()},
    )
    return receipt


def make_plot(summary: pd.DataFrame, target: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["svg.hashsalt"] = "etf-total-return-v1"
    import matplotlib.pyplot as plt

    for asset in ("spy", "qqq"):
        frame = summary[
            summary.asset.eq(asset)
            & summary.years.eq(10)
            & summary.variant.eq("none_core0")
            & summary.complete.gt(0)
        ]
        fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout="constrained")
        y = range(len(frame))
        axes[0].barh(y, frame.median_post_annualized_return * 100, label="Median annual TWR")
        axes[0].plot(frame.min_post_annualized_return * 100, y, "rx", label="Worst annual TWR")
        axes[0].set_yticks(list(y), frame.rule)
        axes[0].axvline(0, color="grey", lw=0.6)
        axes[0].legend(fontsize=8)
        axes[0].set_xlabel("Percent per year, 10 years after actual entry")
        axes[1].barh(
            y, frame.min_post_max_drawdown * 100, color="firebrick", label="Worst NAV drawdown"
        )
        axes[1].plot(
            frame.min_post_maximum_principal_loss * 100, y, "kx", label="Worst principal loss"
        )
        axes[1].set_yticks(
            list(y),
            [f"{int(r.complete)} cohorts / {r.unique_entries} entries" for r in frame.itertuples()],
        )
        axes[1].legend(fontsize=8, loc="lower left", bbox_to_anchor=(0, 1.01))
        axes[1].set_xlabel("Percent; each worst value can come from a different cohort")
        fig.suptitle(
            f"{asset.upper()} cash pool, real dividends, no exit; subsequent buying remains gated\n"
            "Exploratory, overlapping cohorts; valuation gaps retained"
        )
        fig.savefig(target / f"{asset}_10y.png", dpi=160)
        fig.savefig(target / f"{asset}_10y.svg", metadata={"Date": None})
        plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--cash", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, action="append", default=[])
    parser.add_argument("--old-price", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            report(args.source, args.destination, args.cash, args.diagnostic, args.old_price),
            indent=2,
        )
    )
