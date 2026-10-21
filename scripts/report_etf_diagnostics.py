#!/usr/bin/env python3
"""Explain the registered event-order negative result and cash-source sensitivity."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json


def read_verified(root: Path, name: str):
    hashes = json.loads((root / "payloads.json").read_text())
    if sha256_file(root / name) != hashes[name]:
        raise ValueError("diagnostic input changed")
    return pd.read_parquet(root / name) if name.endswith(".parquet") else pd.read_csv(root / name)


def report(main: Path, event: Path, cash: Path, alternate_cash: Path, target: Path) -> dict:
    if target.exists():
        raise ValueError("new diagnostic directory required")
    target.mkdir(parents=True)
    name = "inputs/spy_value_stabilized_60_archive_features.parquet"
    features = read_verified(main, name)
    alternative = read_verified(event, name)
    case = features.loc["2020-02-20":"2020-04-15"].copy()
    case["within_event_value_eligible"] = alternative.event_value_eligible.reindex(case.index)
    case.to_csv(target / "2020_event_sequence.csv", index_label="date")
    first, second = (
        json.loads((main / "payloads.json").read_text()),
        json.loads((event / "payloads.json").read_text()),
    )
    comparisons, changed_columns = [], set()
    cash_and_holdings_exact = True
    for name, digest in second.items():
        if name.startswith("accounts/") and name.endswith(
            ("/daily.parquet", "/journal.parquet", "/metrics.json")
        ):
            if name not in first:
                raise ValueError(f"registered comparison account missing: {name}")
            if sha256_file(main / name) != first[name] or sha256_file(event / name) != digest:
                raise ValueError(f"registered account payload changed: {name}")
            matches = digest == first[name]
            if name.endswith("/daily.parquet") and not matches:
                old, new = read_verified(main, name), read_verified(event, name)
                changed_columns.update(c for c in old.columns if not old[c].equals(new[c]))
                financial = [
                    "equity",
                    "cash",
                    "external_flow",
                    "pre_flow_equity",
                    "shares",
                    "receivable",
                    "commission",
                    "slippage",
                    "gross_dividends",
                    "dividend_tax",
                    "turnover_notional",
                    "twr_return",
                    "twr_nav",
                ]
                try:
                    pd.testing.assert_frame_equal(old[financial], new[financial], check_exact=True)
                except AssertionError:
                    cash_and_holdings_exact = False
            comparisons.append(dict(path=name, exact=matches))
    pd.DataFrame(comparisons).to_csv(target / "event_order_account_comparison.csv", index=False)
    original = read_verified(cash, "all_waiting_results.csv")
    other = read_verified(alternate_cash, "all_waiting_results.csv")
    keys = ["asset", "rule", "origin", "period"]
    paired = original.merge(other, on=keys, suffixes=("", "_alternative"), validate="one_to_one")
    paired["wealth_delta"] = (
        paired.wealth_net_liquidation_alternative - paired.wealth_net_liquidation
    )
    paired.to_csv(target / "cash_source_all_pairs.csv", index=False)
    cash_effect = float(paired.wealth_delta.abs().max())
    result = dict(
        event_financial_files=len(comparisons),
        event_financial_files_exact=all(r["exact"] for r in comparisons),
        daily_changed_columns=sorted(changed_columns),
        daily_cash_holdings_returns_exact=cash_and_holdings_exact,
        journals_exact=all(
            r["exact"] for r in comparisons if r["path"].endswith("/journal.parquet")
        ),
        metrics_exact=all(r["exact"] for r in comparisons if r["path"].endswith("/metrics.json")),
        cash_comparisons=len(paired),
        cash_source_max_absolute_wealth_delta=cash_effect,
        inputs={
            str(p): sha256_file(p / "payloads.json") for p in (main, event, cash, alternate_cash)
        },
        reporter_sha256=sha256_file(Path(__file__)),
        case_selection="2020 diagnostic selected to explain absence of mature joint-entry samples, not to select a parameter",
    )
    plot_case(case, target)
    write_json(target / "receipt.json", result)
    write_json(
        target / "payloads.json",
        {p.name: sha256_file(p) for p in sorted(target.iterdir()) if p.is_file()},
    )
    return result


def plot_case(case, target):
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["svg.hashsalt"] = "etf-event-diagnostic-v1"
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, layout="constrained")
    axes[0].plot(case.index, case.close, color="navy")
    axes[0].set_ylabel("S&P 500 price index")
    axes[1].plot(case.index, case.temperature * 100, color="darkgreen")
    axes[1].axhline(40, color="firebrick", ls="--", label="Buy threshold: strictly below 40%")
    axes[1].set_ylabel("Archive-version PE percentile")
    for date, description in [
        ("2020-03-12", "Pressure starts"),
        ("2020-03-16", "Low valuation"),
        ("2020-03-30", "Stabilization pulse"),
    ]:
        d = pd.Timestamp(date)
        for ax in axes:
            ax.axvline(d, color="grey", lw=0.6, alpha=0.6)
        axes[0].scatter([d], [case.loc[d, "close"]], color="firebrick")
        axes[0].annotate(
            f"{description}: {case.loc[d, 'temperature'] * 100:.2f}%",
            (d, case.loc[d, "close"]),
            xytext=(0, 15 if d.day != 16 else -28),
            textcoords="offset points",
            ha="center",
            fontsize=9,
        )
    axes[1].legend(fontsize=9)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.suptitle(
        "2020: requiring low valuation at the stabilization pulse misses the entry\n"
        "Archived Shiller proxy; sparse history; this case does not establish an optimal threshold"
    )
    fig.savefig(target / "event_sequence_2020.png", dpi=170)
    fig.savefig(target / "event_sequence_2020.svg", metadata={"Date": None})
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    for name in ("main", "event", "cash", "alternate_cash", "destination"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            report(args.main, args.event, args.cash, args.alternate_cash, args.destination),
            indent=2,
        )
    )
