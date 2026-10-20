#!/usr/bin/env python3
"""Recompute only independently identified calendar differences, preserving originals."""

from dataclasses import replace
from pathlib import Path
import argparse
import json

import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.diagnostics import verify_price_ledger
from quant.longterm.ledger import Costs, dec
from quant.longterm.pool_extensions import save_extension_case
from quant.longterm.pool_research import _paired_metrics
from quant.longterm.stages import StageSpec


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve previous corrections")
    audit = json.loads(args.audit.read_text())
    if audit["registration_sha256"] != sha256_file(args.source / "registration.json"):
        raise ValueError("calendar audit belongs to another study")
    registration = json.loads((args.source / "registration.json").read_text())
    experiments = {r["id"]: r for r in registration["experiments"]}
    symbols = {r["id"]: r["index"] for r in registration["universe"]}
    cases = []
    for change in audit["changed_windows"]:
        name = Path(change["asset"]) / change["experiment"] / change["window"]
        original = args.source / name / "record.json"
        row = json.loads(original.read_text())
        if row["status"] != "computed" or any(row[k] != change["old"][k] for k in ("start", "end")):
            raise ValueError("original case does not match audited calendar")
        cases.append((change, name, row, sha256_file(original)))
    defaults = registration["config"]["execution"]
    costs = Costs(
        commission_rate=dec(defaults["commission_rate"]),
        minimum_commission=dec(defaults["minimum_commission"]),
        slippage_bps=dec(defaults["slippage_bps"]),
    )
    args.output.mkdir(parents=True)
    proofs = []
    rows = []
    for change, name, original, fingerprint in cases:
        asset = change["asset"]
        experiment = experiments[change["experiment"]]
        if experiment.get("metric") or experiment.get("execution_override"):
            raise ValueError("this correction requires a separately reviewed valuation/cost case")
        if (
            experiment.get("availability_delay")
            or experiment.get("supplemental_lags")
            or StageSpec(**experiment["stages"]) != StageSpec(**registration["config"]["stages"])
        ):
            raise ValueError("correction cannot silently reuse different signal features")
        if (args.source / "inputs" / f"{asset}_actions.parquet").exists():
            raise ValueError("this correction needs an action-aware audit")
        bars_path = args.source / "inputs" / f"{asset}.parquet"
        features_path = args.source / asset / "stages.parquet"
        bars, features = pd.read_parquet(bars_path), pd.read_parquet(features_path)
        policy = PoolPolicy(**experiment["policy"])
        kwargs = {
            "symbol": symbols[asset],
            "start": change["new"]["start"],
            "end": change["new"]["end"],
            "costs": costs,
        }
        result = run_cash_pool(bars, features, policy, **kwargs)
        control = run_cash_pool(
            bars,
            features,
            replace(policy, entry="unconditional", exit="none", event_tranches=0),
            **kwargs,
        )
        verified = verify_price_ledger(result, bars.close)
        verify_price_ledger(control, bars.close)
        record = (
            original
            | _paired_metrics(result, control)
            | {
                "phase": change["new"]["phase"],
                "correction": "complete_calendar_split_instead_of_nonmissing_factor_count",
                "superseded_record_sha256": fingerprint,
            }
        )
        rows.append(save_extension_case(result, verified, args.output / name, record, args.output))
        proofs.append(
            {
                "asset": asset,
                "experiment": change["experiment"],
                "window": change["window"],
                "old_record_sha256": fingerprint,
                "change": change,
                "bars_sha256": sha256_file(bars_path),
                "features_sha256": sha256_file(features_path),
            }
        )
    table = pd.DataFrame(rows)
    table.to_parquet(args.output / "results.parquet", index=False, compression="zstd")
    table.to_csv(args.output / "results.csv", index=False)
    write_json(
        args.output / "registration.json",
        {
            "source": str(args.source),
            "source_registration_sha256": sha256_file(args.source / "registration.json"),
            "audit_sha256": sha256_file(args.audit),
            "code": code_revision(),
            "script_sha256": sha256_file(Path(__file__)),
            "cases": proofs,
            "selection": "all_calendar_differences_not_performance_selected",
        },
    )
    write_json(args.output / "summary.json", {"computed": len(rows), "all_ledgers_verified": True})
    write_json(
        args.output / "payloads.json",
        {
            str(p.relative_to(args.output)): sha256_file(p)
            for p in sorted(args.output.rglob("*"))
            if p.is_file() and p.name != "registration.json"
        },
    )
    print(json.dumps({"computed": len(rows), "directory": str(args.output)}))


if __name__ == "__main__":
    main()
