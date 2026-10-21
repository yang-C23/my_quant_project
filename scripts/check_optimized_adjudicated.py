#!/usr/bin/env python3
"""Check optimized output against prior adjudications, without rewriting a run."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("optimized", type=Path)
    parser.add_argument("corrections", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve every previous comparison")
    correction = json.loads((args.corrections / "registration.json").read_text())
    if correction["source_registration_sha256"] != sha256_file(args.original / "registration.json"):
        raise AssertionError("adjudication is not bound to the original study")
    cases = {
        f"{row['asset']}/{row['experiment']}/{row['window']}": row for row in correction["cases"]
    }
    payloads = json.loads((args.original / "payloads.json").read_text())
    optimized_assets = {
        p.name for p in args.optimized.iterdir() if p.is_dir() and p.name != "inputs"
    }
    exact, changes, checked = 0, [], 0
    for relative, old_hash in payloads.items():
        parts = Path(relative).parts
        if len(parts) < 2 or parts[0] not in optimized_assets | {"inputs"}:
            continue
        old_path, new_path = args.original / relative, args.optimized / relative
        if sha256_file(old_path) != old_hash:
            raise AssertionError(f"original changed: {relative}")
        checked += 1
        if sha256_file(new_path) == old_hash:
            exact += 1
            continue
        case = str(Path(relative).parent)
        if case in cases:
            expected_path = args.corrections / relative
            if parts[-1] == "record.json":
                expected, actual = (json.loads(p.read_text()) for p in (expected_path, new_path))
                extras = set(expected) - set(actual)
                if extras != {"correction", "superseded_record_sha256", "price_profit_net_costs"}:
                    raise AssertionError(f"unexpected adjudication record fields: {extras}")
                if any(expected[key] != value for key, value in actual.items()):
                    raise AssertionError(f"corrected record value differs: {relative}")
                if expected["superseded_record_sha256"] != cases[case]["old_record_sha256"]:
                    raise AssertionError("adjudicated case lost its superseded identity")
                reason = "exact_record_values_prior_adjudication_has_three_extra_provenance_fields"
            else:
                if sha256_file(expected_path) != sha256_file(new_path):
                    raise AssertionError(
                        f"optimized differs from corrected financial file: {relative}"
                    )
                reason = "byte_exact_to_previously_adjudicated_calendar_case"
        elif parts[-1].startswith("supplemental") and parts[-1].endswith(".json"):
            expected, actual = (json.loads(p.read_text()) for p in (old_path, new_path))
            # This field was introduced by b61c76f, before the performance branch.
            # It explicitly records the disabled source-bound sensitivity.
            for row in expected:
                if row.get("factor") == "positions":
                    row["conservative_publication_bounds"] = None
            if expected != actual:
                raise AssertionError(f"unexpected source-evidence difference: {relative}")
            reason = "pre_performance_provenance_field_conservative_publication_bounds_null"
        elif relative == "nasdaq100/results.parquet":
            expected, actual = (pd.read_parquet(p) for p in (old_path, new_path))
            for name in cases:
                record = json.loads((args.corrections / name / "record.json").read_text())
                mask = expected.experiment.eq(record["experiment"]) & expected.window.eq(
                    record["window"]
                )
                if mask.sum() != 1:
                    raise AssertionError("corrected aggregate case is not unique")
                for column in expected.columns:
                    if column in record:
                        expected.loc[mask, column] = record[column]
            pd.testing.assert_frame_equal(expected, actual, check_exact=True)
            reason = "aggregate_exact_after_six_previously_adjudicated_calendar_rows"
        else:
            raise AssertionError(f"unexplained optimization difference: {relative}")
        changes.append({"path": relative, "reason": reason})
    write_json(
        args.output,
        {
            "ok": True,
            "original_registration_sha256": sha256_file(args.original / "registration.json"),
            "optimized_registration_sha256": sha256_file(args.optimized / "registration.json"),
            "correction_registration_sha256": sha256_file(args.corrections / "registration.json"),
            "script_sha256": sha256_file(Path(__file__)),
            "files_checked": checked,
            "byte_exact_to_original": exact,
            "prior_adjudicated_cases": len(cases),
            "financial_precision": "exact_bytes_or_exact_values;no_numeric_tolerance",
            "initial_negative_comparison_preserved": str(
                args.optimized / "performance_equivalence.json"
            ),
            "declared_pre_optimization_differences": changes,
        },
    )
    print(
        f"{checked} files checked; {exact} original-byte identical; {len(changes)} declared prior changes"
    )


if __name__ == "__main__":
    main()
