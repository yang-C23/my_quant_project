#!/usr/bin/env python3
"""Audit every monthly funding window for all three action-reviewed ETF cases."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import shutil

import pandas as pd

from quant.config import load_config
from quant.data.snapshots import sha256_file, utc_now, write_json
from quant.etl.restart import code_revision
from quant.longterm.action_audit import verify_action_ledger
from quant.longterm.cash_pool import PoolPolicy, capital_metrics, run_cash_pool
from quant.longterm.engine import Strategy, run_strategy
from quant.longterm.ledger import Costs, dec
from quant.longterm.pool_analysis import window_summary
from quant.longterm.pool_extensions import load_study_asset, save_extension_case
from quant.longterm.pool_research import _paired_metrics
from quant.longterm.stages import StageSpec, stage_features


def monthly_windows(dates: pd.DatetimeIndex, years: list[int]) -> list[dict]:
    """Keep full calendar years, including monthly endpoints and the latest session."""
    if not dates.is_unique or not dates.is_monotonic_increasing or not len(dates):
        raise ValueError("nonempty unique ordered account calendar required")
    output = []
    for horizon in years:
        first_end = dates[0] + pd.DateOffset(years=horizon)
        if first_end > dates[-1]:
            continue
        ends = pd.date_range(first_end, dates[-1], freq="ME").union(dates[-1:])
        for target_end in ends:
            target_start = target_end - pd.DateOffset(years=horizon)
            selected = dates[(dates >= target_start) & (dates <= target_end)]
            if (
                len(selected) < 60
                or (selected[0] - target_start).days > 14
                or (target_end - selected[-1]).days > 14
            ):
                raise ValueError("missing price calendar cannot shorten a multi-year window")
            output.append(
                {
                    "id": f"rolling_{horizon}y_{target_end.date()}",
                    "start": str(selected[0].date()),
                    "end": str(selected[-1].date()),
                }
            )
    return output


def run_asset(job: dict) -> list[dict]:
    root, name = Path(job["root"]), job["asset"]
    registered = json.loads((root / "registration.json").read_text())
    primary, config = registered["primary_config"], registered["config"]
    bars, signals, actions = load_study_asset(root, name)
    if actions is None:
        raise ValueError("reviewed action inputs required for ETF account audit")
    stages = stage_features(signals, StageSpec(**primary["stages"]))
    costs = Costs(
        commission_rate=dec(primary["execution"]["commission_rate"]),
        minimum_commission=dec(primary["execution"]["minimum_commission"]),
        slippage_bps=dec(primary["execution"]["slippage_bps"]),
    )
    first = pd.Timestamp(job["funding_start"])
    windows = monthly_windows(bars.index[bars.index >= first], config["rolling_years"])
    rows = []
    control_policy = PoolPolicy(**primary["funding"], entry="unconditional", exit="none")
    for window in windows:
        kwargs = {
            "symbol": job["symbol"],
            "start": window["start"],
            "end": window["end"],
            "actions": actions,
            "lot": dec(100),
            "costs": costs,
            "price_basis": "raw",
            "execution": "next_close",
        }
        control = run_cash_pool(bars, stages, control_policy, **kwargs)
        for experiment in registered["experiments"]:
            identifier = experiment["id"]
            if identifier == "pool_unconditional_core0":
                result = control
            elif experiment["engine"] == "legacy":
                result = run_strategy(
                    bars,
                    stages,
                    Strategy(name=experiment["legacy"], **primary["funding"]),
                    **kwargs,
                )
                result.metrics.update(capital_metrics(result.daily, result.journal))
            else:
                result = run_cash_pool(bars, stages, PoolPolicy(**experiment["policy"]), **kwargs)
            audit = verify_action_ledger(result, bars.close, actions, costs)
            record = {
                "asset": name,
                "experiment": identifier,
                "window": window["id"],
                "status": "computed",
                "phase": "monthly_overlapping_retrospective_seen_history",
                "formal_accepted": False,
                "basis": "named_ETF_actual_prices_with_reviewed_actions",
                **_paired_metrics(result, control),
            }
            case = root / name / identifier / window["id"]
            rows.append(save_extension_case(result, audit, case, record, root))
        write_json(root / name / "progress.json", {"cases": len(rows), "last_window": window})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("primary", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/etf_monthly_windows.yaml"))
    parser.add_argument("--replay-run", type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        raise ValueError("preserve earlier monthly-window studies")
    config = load_config(args.config)
    prior = json.loads((args.primary / "registration.json").read_text())
    experiments = {row["id"]: row for row in prior["experiments"]}
    coverage = {
        row["asset"]: row for row in json.loads((args.primary / "coverage.json").read_text())
    }
    paths = [
        args.primary / "inputs" / f"{asset}{suffix}.parquet"
        for asset in config["assets"]
        for suffix in ("", "_actions")
    ]
    registration = {
        "registered_at": utc_now(),
        "primary": str(args.primary),
        "primary_registration_sha256": sha256_file(args.primary / "registration.json"),
        "primary_config": prior["config"],
        "config": config,
        "config_sha256": sha256_file(args.config),
        "experiments": [experiments[name] for name in config["experiments"]],
        "input_hashes": {path.name: sha256_file(path) for path in paths},
        "code": code_revision(),
        "formal_accepted": False,
    }
    if args.replay_run:
        original = json.loads((args.replay_run / "registration.json").read_text())
        for key in ("primary_registration_sha256", "config", "input_hashes", "experiments"):
            if registration[key] != original[key]:
                raise ValueError(f"monthly-window replay mismatch: {key}")
        if registration["code"]["sources"] != original["code"]["sources"]:
            raise ValueError("monthly-window replay requires identical source bytes")
        registration = original
    args.destination.mkdir(parents=True)
    (args.destination / "inputs").mkdir()
    for path in paths:
        shutil.copy2(path, args.destination / "inputs" / path.name)
    write_json(args.destination / "registration.json", registration)
    jobs = [
        {
            "root": str(args.destination),
            "asset": asset,
            "symbol": coverage[asset]["symbol"],
            "funding_start": coverage[asset]["funding_start_after_shared_warmup"],
        }
        for asset in config["assets"]
    ]
    with ProcessPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run_asset, jobs))
    table = pd.DataFrame([row for rows in results for row in rows])
    table.to_parquet(args.destination / "results.parquet", compression="zstd")
    table.to_csv(args.destination / "results.csv", index=False)
    window_summary(table).to_csv(args.destination / "windows_all.csv", index=False)
    summary = {
        "accounts": len(table),
        "statuses": table.status.value_counts().to_dict(),
        "all_ledgers_verified": bool(table.independent_ledger_verified.all()),
        "formal_accepted": False,
    }
    write_json(args.destination / "summary.json", summary)
    payloads = {
        str(path.relative_to(args.destination)): sha256_file(path)
        for path in sorted(args.destination.rglob("*"))
        if path.is_file() and path.name not in {"registration.json", "progress.json"}
    }
    write_json(args.destination / "payloads.json", payloads)
    if args.replay_run:
        old = json.loads((args.replay_run / "payloads.json").read_text())
        changed = sorted(k for k in set(old) | set(payloads) if old.get(k) != payloads.get(k))
        write_json(
            args.destination / "replay.json",
            {"identical": not changed, "changed_files": changed, "payloads": len(payloads)},
        )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
