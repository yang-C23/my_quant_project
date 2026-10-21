#!/usr/bin/env python3
"""Derive all paired comparisons from frozen cohort output; never select winners."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json


def paired_tables(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Require identical cohorts for an exit's effect and an entry's waiting cost."""
    keys = ["asset", "rule", "scope", "origin", "entry", "years", "end"]
    full = table[table.status.eq("complete")].copy()
    reference = full[full.variant.eq("none_core0")]
    columns = keys + [
        "ending_wealth",
        "post_max_drawdown",
        "post_annualized_return",
        "post_maximum_principal_loss",
        "ending_principal_loss",
        "contributed",
    ]
    joined = full.merge(
        reference[columns], on=keys, suffixes=("", "_reference"), validate="many_to_one"
    )
    if not joined.contributed.eq(joined.contributed_reference).all():
        raise ValueError("paired comparisons do not have equal funding")
    for name in [
        "ending_wealth",
        "post_max_drawdown",
        "post_annualized_return",
        "post_maximum_principal_loss",
    ]:
        joined[name + "_delta"] = joined[name] - joined[name + "_reference"]
    summaries = []
    for group_key, f in joined.groupby(["asset", "rule", "scope", "variant", "years"]):
        row = dict(zip(["asset", "rule", "scope", "variant", "years"], group_key, strict=True))
        row.update(
            pairs=len(f),
            unique_entries=f.entry.nunique(),
            improved_wealth=int(f.ending_wealth_delta.gt(0.01).sum()),
            reduced_drawdown=int(f.post_max_drawdown_delta.gt(1e-12).sum()),
            prevented_terminal_loss=int(
                (f.ending_principal_loss_reference & ~f.ending_principal_loss).sum()
            ),
            introduced_terminal_loss=int(
                (~f.ending_principal_loss_reference & f.ending_principal_loss).sum()
            ),
        )
        for name in [
            "ending_wealth",
            "post_max_drawdown",
            "post_annualized_return",
            "post_maximum_principal_loss",
        ]:
            row["median_" + name + "_delta"] = float(f[name + "_delta"].median())
        summaries.append(row)
    return joined, pd.DataFrame(summaries)


def report(source: Path, target: Path, sensitivity: Path | None) -> dict:
    if target.exists():
        raise ValueError("new report directory required")
    target.mkdir(parents=True)
    payloads = json.loads((source / "payloads.json").read_text())
    verified = {}
    for name in (
        "all_cohort_results.csv",
        "summary.csv",
        "waiting_all.csv",
        "coverage.json",
        "cohorts.json",
    ):
        actual = sha256_file(source / name)
        if actual != payloads[name]:
            raise ValueError(f"source summary changed: {name}")
        verified[name] = actual
    table = pd.read_csv(source / "all_cohort_results.csv")
    summary = pd.read_csv(source / "summary.csv")
    pairs, effects = paired_tables(table)
    pairs.to_csv(target / "paired_accounts.csv", index=False)
    effects.to_csv(target / "paired_effects.csv", index=False)
    # Every worst case is preserved, including tied worst outcomes.
    worst = []
    full = table[table.status.eq("complete") & table.variant.eq("none_core0")]
    for metric in ("post_annualized_return", "post_max_drawdown", "post_maximum_principal_loss"):
        for _, f in full.groupby(["asset", "rule", "years"]):
            worst.append(f[f[metric].eq(f[metric].min())].assign(worst_by=metric))
    pd.concat(worst, ignore_index=True).to_csv(target / "all_worst_cases.csv", index=False)
    waiting = pd.read_csv(source / "waiting_all.csv")
    wait_rows = []
    for keys, f in waiting.groupby(["asset", "rule", "scope", "months"]):
        observed = f[f.observation_available.eq(True)]
        still = observed[observed.still_waiting.eq(True)]
        row = dict(zip(["asset", "rule", "scope", "months"], keys, strict=True))
        row.update(
            origins=len(f),
            observed=len(observed),
            still_waiting=len(still),
            median_gap_while_waiting=float(still.wealth_gap_vs_origin_pool.median()),
            worst_gap_while_waiting=float(still.wealth_gap_vs_origin_pool.min()),
            best_gap_while_waiting=float(still.wealth_gap_vs_origin_pool.max()),
        )
        wait_rows.append(row)
    pd.DataFrame(wait_rows).to_csv(target / "waiting_summary.csv", index=False)
    if sensitivity:
        alternative = pd.read_csv(sensitivity / "all_cohort_results.csv")
        expected = json.loads((sensitivity / "payloads.json").read_text())
        if (
            sha256_file(sensitivity / "all_cohort_results.csv")
            != expected["all_cohort_results.csv"]
        ):
            raise ValueError("sensitivity summary hash mismatch")
        keys = ["asset", "rule", "scope", "origin", "variant", "years"]
        compare = table[table.asset.eq("sp500")].merge(
            alternative,
            on=keys,
            suffixes=("", "_alt"),
            validate="one_to_one",
            how="outer",
            indicator=True,
        )
        if not compare._merge.eq("both").all():
            raise ValueError("source sensitivity has different registered cohorts")
        for name in ("entry", "end", "status"):
            compare[name + "_changed"] = (
                compare[name].fillna("missing").ne(compare[name + "_alt"].fillna("missing"))
            )
        compare["wealth_difference"] = compare.ending_wealth_alt - compare.ending_wealth
        compare.to_csv(target / "source_sensitivity_all.csv", index=False)
        write_json(
            target / "source_sensitivity.json",
            dict(
                comparisons=len(compare),
                entry_changed=int(compare.entry_changed.sum()),
                endpoint_changed=int(compare.end_changed.sum()),
                status_changed=int(compare.status_changed.sum()),
                maximum_absolute_wealth_difference=float(compare.wealth_difference.abs().max()),
                maximum_absolute_post_annualized_difference=float(
                    (compare.post_annualized_return_alt - compare.post_annualized_return)
                    .abs()
                    .max()
                ),
            ),
        )
    # A small scientific overview shows all primary entry families, not winners.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for asset in ("sp500", "nasdaq100"):
        f = summary[
            summary.asset.eq(asset)
            & summary.scope.eq("primary")
            & summary.variant.eq("none_core0")
            & summary.years.eq(10)
            & summary.complete.gt(0)
        ]
        fig, axes = plt.subplots(1, 2, figsize=(12, max(4, len(f) * 0.4)), layout="constrained")
        y = list(range(len(f)))
        axes[0].barh(y, f.median_post_annualized_return * 100, label="Median annualized TWR")
        axes[0].plot(f.worst_post_annualized_return * 100, y, "rx", label="Worst annualized TWR")
        axes[0].set_yticks(y, f.rule)
        axes[0].axvline(0, color="grey", lw=0.6)
        axes[0].set_xlabel("Percent per year; complete 10-year periods after first fill")
        axes[0].legend(fontsize=8)
        axes[1].barh(y, f.worst_post_max_drawdown * 100, color="firebrick", label="Worst drawdown")
        axes[1].plot(
            f.worst_post_maximum_principal_loss * 100, y, "kx", label="Worst loss vs contributions"
        )
        axes[1].set_yticks(
            y,
            [f"{r.complete} cohorts / {r.unique_complete_entries} entries" for r in f.itertuples()],
        )
        axes[1].set_xlabel("Percent; marginal worst cases may differ")
        axes[1].legend(fontsize=8)
        fig.suptitle(f"{asset}: price-index exploration, dividends excluded; overlapping cohorts")
        fig.savefig(target / f"{asset}_10y.png", dpi=170)
        fig.savefig(target / f"{asset}_10y.svg")
        plt.close(fig)
    receipt = dict(
        source=str(source),
        registration_sha256=sha256_file(source / "registration.json"),
        verified=verified,
        reporter_sha256=sha256_file(Path(__file__)),
        rows=len(table),
        paired_rows=len(pairs),
        selection="all_registered_complete_cohorts_plus_censoring_report",
    )
    write_json(target / "receipt.json", receipt)
    write_json(
        target / "payloads.json",
        {
            str(p.relative_to(target)): sha256_file(p)
            for p in sorted(target.iterdir())
            if p.is_file()
        },
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--sensitivity", type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.source, args.destination, args.sensitivity), indent=2))
