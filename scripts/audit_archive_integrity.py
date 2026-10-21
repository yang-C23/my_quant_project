#!/usr/bin/env python3
"""Recheck archive content digests and quantify impact on frozen valuation inputs."""

import argparse
import json
from pathlib import Path

import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.longterm.etf_inputs import archive_observations
from quant.longterm.vintage_valuation import archive_temperature


def audit(source: Path, run: Path, target: Path) -> dict:
    if target.exists():
        raise ValueError("new destination required")
    target.mkdir(parents=True)
    valid, evidence = archive_observations(source)
    write_json(target / "archive_admission.json", evidence)
    hashes = json.loads((run / "payloads.json").read_text())
    names = ["sp500_archive_temperature.parquet", "spy_signals.parquet", "exchange_closes.parquet"]
    for name in names:
        if sha256_file(run / "inputs" / name) != hashes["inputs/" + name]:
            raise ValueError("frozen source changed")
    old = pd.read_parquet(run / "inputs" / names[0])
    prices = pd.read_parquet(run / "inputs" / names[1]).close
    times = pd.read_parquet(run / "inputs" / names[2]).close_time
    new = archive_temperature(prices, valid, decision_times=times)
    columns = ["temperature", "pe", "earnings", "history_count"]
    pd.testing.assert_frame_equal(old.loc[prices.index, columns], new[columns], check_exact=True)
    # Every strategy consumes only the temperature column from this adapter.
    # Rejecting a version whose earnings were already stale must change no signal.
    result = dict(
        accepted_vintages=valid.vintage.nunique(),
        rejections=[r for r in evidence if r["status"] != "parsed"],
        decision_sessions=len(prices),
        financial_columns_exact=True,
        signal_input_changed=False,
        frozen_run=str(run),
        frozen_payloads_sha256=sha256_file(run / "payloads.json"),
    )
    write_json(target / "impact.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.source, args.run, args.destination), indent=2))
