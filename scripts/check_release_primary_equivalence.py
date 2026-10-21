#!/usr/bin/env python3
"""Compare frozen release-audit controls, declaring historical symbol aliases."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("primary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve earlier checks including negative ones")
    registered = json.loads((args.primary / "registration.json").read_text())
    symbols = {x["id"]: x["index"] for x in registered["universe"]}
    coverage = {x["asset"]: x for x in json.loads((args.primary / "coverage.json").read_text())}
    table = pd.read_parquet(args.source / "results.parquet")
    rows = []
    for _, row in table[table["mode"].eq("registered_assumption")].iterrows():
        a = args.primary / row.asset / row.experiment / row.window
        b = args.source / row.result_directory
        checks = {
            name: sha256_file(a / name) == sha256_file(b / name)
            for name in ("daily.parquet", "metrics.json", "strategy.json", "ledger_audit.json")
        }
        left, right = (pd.read_parquet(p / "journal.parquet") for p in (a, b))
        canonical = coverage[row.asset].get("symbol", symbols[row.asset])
        observed = set(right.symbol.dropna()) if "symbol" in right else set()
        if not observed.issubset({row.asset, canonical}):
            raise AssertionError("unknown symbol identity cannot be normalized")
        exact_before_alias = sha256_file(a / "journal.parquet") == sha256_file(
            b / "journal.parquet"
        )
        if "symbol" in right:
            right["symbol"] = right.symbol.replace({row.asset: canonical})
        pd.testing.assert_frame_equal(left, right, check_exact=True)
        if not all(checks.values()):
            raise AssertionError(f"non-alias financial difference: {row.asset} {row.window}")
        rows.append(
            {
                "asset": row.asset,
                "experiment": row.experiment,
                "window": row.window,
                "exact_files": checks,
                "journal_bytes_exact_before_alias": exact_before_alias,
                "canonical_symbol": canonical,
                "historical_alias": row.asset,
                "all_journal_values_exact_after_explicit_alias": True,
            }
        )
    write_json(
        args.output,
        {
            "script_sha256": sha256_file(Path(__file__)),
            "source_registration_sha256": sha256_file(args.source / "registration.json"),
            "primary_registration_sha256": sha256_file(args.primary / "registration.json"),
            "accounts": len(rows),
            "all_economic_values_exact": bool(rows),
            "byte_identity_claimed_for_journal": False,
            "comparisons": rows,
        },
    )
    print(f"{len(rows)} controls match exactly after declared source-to-canonical symbol mapping")


if __name__ == "__main__":
    main()
