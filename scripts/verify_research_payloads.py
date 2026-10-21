#!/usr/bin/env python3
"""Read and rehash every original/replayed payload, including exact Decimal journals."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path

from quant.data.snapshots import sha256_file, write_json


def check_pair(item):
    source, replay, name, digest = item
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("manifest path escapes run")
    first, second = sha256_file(source / name), sha256_file(replay / name)
    return dict(
        run=source.name,
        path=name,
        expected=digest,
        original=first,
        replay=second,
        exact=first == second == digest,
    )


def verify(runs: list[Path], target: Path, workers: int) -> dict:
    if target.exists() or not 1 <= workers <= int(os.getenv("QUANT_WORKERS", workers)):
        raise ValueError("new output and admitted worker count required")
    target.mkdir(parents=True)
    items, evidence = [], []
    for source in runs:
        replay = source.with_name(source.name + "-replay")
        original = json.loads((source / "payloads.json").read_text())
        repeated = json.loads((replay / "payloads.json").read_text())
        if original != repeated:
            raise ValueError("registered payloads differ before rehash")
        items.extend((source, replay, name, digest) for name, digest in original.items())
        ledger_audits = []
        for name in original:
            if name.endswith("/ledger_audit.json"):
                ledger_audits.append(json.loads((source / name).read_text())["ok"])
        if ledger_audits and not all(ledger_audits):
            raise ValueError("independent ledger failure")
        evidence.append(
            dict(
                run=source.name,
                paired_payloads=len(original),
                independent_accounts=len(ledger_audits),
                registration_sha256=sha256_file(source / "registration.json"),
                code=json.loads((source / "registration.json").read_text())["code"]["commit"],
            )
        )
    failed, checked = [], 0
    with (target / "actual_file_hashes.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["run", "path", "expected", "original", "replay", "exact"]
        )
        writer.writeheader()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for row in pool.map(check_pair, items):
                writer.writerow(row)
                checked += 1
                if not row["exact"]:
                    failed.append(row)
    result = dict(
        exact=not failed,
        paired_payloads=checked,
        actual_files_rehashed=2 * checked,
        failures=failed,
        runs=evidence,
        workers=workers,
        verifier_sha256=sha256_file(Path(__file__)),
    )
    write_json(target / "acceptance.json", result)
    if failed:
        raise AssertionError("actual payload differs from registered hash")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--workers", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.run, args.destination, args.workers), indent=2))
