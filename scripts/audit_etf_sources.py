#!/usr/bin/env python3
"""Offline source conflicts, raw-price units and non-forced source alternatives."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.longterm.etf_sources import (
    calendar_check,
    chart_prices,
    combine_distribution_evidence,
    issuer_table_actions,
    local_dates,
    nasdaq_actions,
    ssga_actions,
)


def audit(data_root: Path, target: Path) -> dict:
    if target.exists():
        raise ValueError("new audit directory required")
    target.mkdir(parents=True)
    source = data_root / "source_probes/us-etf-20261021"
    ssga = data_root / "source_probes/sp500-long-20261021/ssga_distributions.raw"
    calendar = data_root / "audits/entry-horizons-20261021/xnys-sessions.json"
    sessions = pd.DatetimeIndex(json.loads(calendar.read_text())["sessions"])
    files, rows, overrides = [ssga, calendar], [], []
    for ticker in ("SPY", "QQQ", "BIL", "SPHD"):
        path = source / f"yahoo_{ticker.lower()}.raw"
        files.append(path)
        bars, splits = chart_prices(path, ticker, "2026-10-19")
        check = calendar_check(bars, sessions)
        row = dict(symbol=ticker, first=str(bars.index[0].date()), rows=len(bars), **check)
        row["split_events"] = len(splits)
        if ticker in {"SPY", "QQQ"}:
            price_file = source / f"nasdaq_{ticker.lower()}_price_check.raw"
            files.append(price_file)
            other = pd.DataFrame(json.loads(price_file.read_text())["data"]["tradesTable"]["rows"])
            other.index = pd.to_datetime(other.pop("date"), format="%m/%d/%Y")
            for name in other.columns:
                other[name] = (
                    other[name]
                    .str.replace(r"[$,]", "", regex=True)
                    .replace("N/A", float("nan"))
                    .astype(float)
                )
            comparison = bars[["close"]].join(other[["close"]], rsuffix="_exchange").dropna()
            comparison["difference"] = comparison.close - comparison.close_exchange
            comparison.to_csv(target / f"{ticker}_all_price_overlaps.csv", index_label="date")
            disagreements = comparison[comparison.difference.abs() > 0.0001]
            row.update(price_overlaps=len(comparison), price_conflicts=len(disagreements))
            for date in disagreements.index:
                for column in ("open", "high", "low", "close"):
                    if pd.isna(other.loc[date, column]):
                        raise ValueError("alternative price has missing OHLC field")
                    overrides.append(
                        dict(
                            asset=ticker.lower(),
                            table="bars",
                            column=column,
                            date=str(date.date()),
                            expected=float(bars.loc[date, column]),
                            value=float(other.loc[date, column]),
                            evidence=str(price_file.relative_to(data_root)),
                        )
                    )
        if ticker == "QQQ":
            publisher = source / "qqq_issuer_search_evidence.txt"
            exchange = source / "qqq_nasdaq_div.raw"
            files += [publisher, exchange]
            actions, conflicts = combine_distribution_evidence(
                issuer_table_actions(publisher, ticker, "2026-10-19"),
                nasdaq_actions(exchange, ticker, "1999-03-10", "2026-10-19"),
            )
            conflicts.to_csv(target / "QQQ_issuer_exchange_conflicts.csv", index=False)
        elif ticker in {"SPY", "BIL"}:
            if ticker == "BIL":
                try:
                    ssga_actions(ssga, ticker, "2026-10-19")
                except ValueError as exc:
                    row["full_history_rejection"] = str(exc)
                row["accepted_actions_from"] = "2008-04-01"
            actions = ssga_actions(
                ssga, ticker, "2026-10-19", start="2008-04-01" if ticker == "BIL" else None
            )
        else:
            row["distribution_status"] = "blocked_incomplete_issuer_payment_history"
            rows.append(row)
            continue
        raw = json.loads(path.read_text())["chart"]["result"][0]
        vendor = pd.DataFrame(list(raw["events"]["dividends"].values()))
        vendor["ex_date"] = local_dates(vendor.date)
        if ticker == "BIL":
            vendor = vendor[vendor.ex_date.ge("2008-04-01")].copy()
        # Only comparison amounts are restored to the actual pre-split units.
        for split in splits.itertuples():
            vendor.loc[vendor.ex_date < split.ex_date, "amount"] *= split.ratio
        comparison = actions.merge(
            vendor[["ex_date", "amount"]], on="ex_date", how="outer", indicator=True
        )
        comparison["difference"] = comparison.per_share - comparison.amount
        comparison.to_csv(target / f"{ticker}_dividend_overlaps.csv", index=False)
        row.update(
            issuer_dividends=len(actions),
            vendor_only_events=int(comparison._merge.eq("right_only").sum()),
            issuer_only_events=int(comparison._merge.eq("left_only").sum()),
            amount_conflicts_over_vendor_rounding=int(
                comparison.difference.abs().gt(0.00051).sum()
            ),
        )
        # This sensitivity changes conflicting amounts only, preserving issuer pay dates.
        if ticker == "SPY":
            for event in comparison[comparison.difference.abs().gt(0.00051)].itertuples():
                overrides.append(
                    dict(
                        asset="spy",
                        table="actions",
                        column="per_share",
                        date=str(event.ex_date.date()),
                        expected=event.per_share,
                        value=event.amount,
                        evidence=str(path.relative_to(data_root)),
                    )
                )
        rows.append(row)
    write_json(target / "source_alternatives.json", overrides)
    pd.DataFrame(rows).to_csv(target / "coverage.csv", index=False)
    receipt = dict(
        formal_accepted=False,
        price_tolerance=0.0001,
        dividend_rounding_band=0.00051,
        sources={str(p.relative_to(data_root)): sha256_file(p) for p in files},
        evidence=rows,
    )
    write_json(target / "receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.data_root, args.destination), indent=2))
