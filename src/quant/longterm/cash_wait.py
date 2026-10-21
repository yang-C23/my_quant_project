"""Actual short-Treasury ETF cash waiting, including payment dates and costs."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import pandas as pd

from quant.data.snapshots import sha256_file, utc_now, write_json
from quant.etl.restart import code_revision
from quant.longterm.engine import Strategy
from quant.longterm.entry_horizons import execute_job
from quant.longterm.etf_sources import calendar_check, chart_prices, ssga_actions, validate_actions
from quant.longterm.ledger import Costs, dec, money


def liquidation_quote(last: pd.Series, price: float, costs: Costs) -> dict:
    """Net proceeds after sale settlement; outstanding dividends remain separate.

    No fractional holdings are permitted in this actual whole-share scenario.
    This terminal liquidation quote does not rewrite earlier account records.
    """
    shares = dec(last.shares)
    if shares != shares.to_integral_value():
        raise ValueError("cash-in-lieu not verified for fractional BIL shares")
    notional = money(shares * dec(price) * (1 - costs.slippage_bps / 10000))
    fee = costs.fee(notional)
    cash = money(dec(last.cash) + notional - fee)
    receivable = dec(last.receivable)
    return dict(
        cash_after_sale_settlement=float(cash),
        unpaid_dividend_receivable=float(receivable),
        wealth_net_liquidation=float(cash + receivable),
        terminal_sale_fee=float(fee),
        terminal_sale_slippage=float(money(shares * dec(price)) - notional),
    )


def build_wait_jobs(parent: Path, root: Path, config: dict, bars: pd.DataFrame):
    """Cash products cannot be backfilled before inception; retain those exclusions."""
    cohorts = json.loads((parent / "cohorts.json").read_text())
    jobs, comparisons = {}, []
    for cohort in cohorts:
        if cohort["asset"] not in config["assets"] or cohort["years"] != 5:
            continue
        origin = pd.Timestamp(cohort["origin"])
        targets = [(f"{m}m", origin + pd.DateOffset(months=m)) for m in config["waiting_months"]]
        targets.append(("until_entry", pd.Timestamp(cohort["entry"] or bars.index[-1])))
        for label, target in targets:
            item = {k: cohort[k] for k in ("asset", "rule", "origin", "entry", "wait_days")}
            item.update(period=label, baseline_account=cohort["accounts"]["origin_pool_hold"])
            if origin < bars.index[config["minimum_listed_sessions"]]:
                comparisons.append(item | {"status": "BIL_not_yet_eligible"})
                continue
            if origin < pd.Timestamp(config["actions_from"]):
                comparisons.append(item | {"status": "BIL_issuer_payment_date_invalid"})
                continue
            position = bars.index.searchsorted(target)
            end = bars.index[min(position, len(bars) - 1)]
            if end <= origin:
                comparisons.append(item | {"status": "no_wait"})
                continue
            spec = dict(
                asset="bil",
                feature="unconditional",
                symbol="BIL",
                lot="2",
                engine="legacy",
                policy=asdict(Strategy(name="lump_sum", **config["funding"])),
                start=str(origin.date()),
                end=str(end.date()),
                costs=config["execution"],
            )
            key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:20]
            jobs[key] = spec | {"id": key, "root": str(root)}
            status = "right_censored" if position == len(bars) else "complete"
            if label == "until_entry" and cohort["entry"] is None:
                status = "no_entry"
            comparisons.append(
                item
                | dict(
                    id=key,
                    end=str(end.date()),
                    status=status,
                    still_waiting=cohort["entry"] is None or pd.Timestamp(cohort["entry"]) >= end,
                )
            )
    for i, job in enumerate(jobs.values()):
        job["prefix_check"] = i in {0, len(jobs) // 2, len(jobs) - 1}
    return list(jobs.values()), comparisons


def run_wait_study(
    data_root: Path, root: Path, config_path: Path, workers: int, *, replay: Path | None = None
) -> dict:
    """Every account is exact-audited; runs are immutable and fully replayable."""
    if root.exists() or workers < 1 or workers > int(os.getenv("QUANT_WORKERS", workers)):
        raise ValueError("new run and admitted worker count required")
    started = time.monotonic()
    config = json.loads(config_path.read_text())
    parent = data_root / "research" / config["parent_run"]
    root.mkdir(parents=True)
    if replay:
        registration = json.loads((replay / "registration.json").read_text())
        if (
            registration["config"] != config
            or registration["code"]["sources"] != code_revision()["sources"]
        ):
            raise ValueError("replay code/config changed")
        for name, digest in registration["inputs"].items():
            if sha256_file(replay / name) != digest:
                raise ValueError("frozen input changed")
        shutil.copytree(replay / "inputs", root / "inputs")
    else:
        base = root / "inputs"
        base.mkdir()
        source_dir = data_root / config["source_directory"]
        prices = source_dir / "yahoo_bil.raw"
        distributions = data_root / config["ssga_distribution_file"]
        calendar = data_root / config["calendar_file"]
        proof = source_dir / "bil_split_corroboration.json"
        bars, splits = chart_prices(prices, "BIL", config["cutoff"])
        corroboration = json.loads(proof.read_text())
        if (
            len(splits) != 1
            or splits.ratio.iloc[0] != corroboration["ratio"]
            or str(splits.ex_date.iloc[0].date()) != corroboration["effective_date"]
        ):
            raise ValueError("BIL split does not match issuer release")
        actions = validate_actions(
            pd.concat(
                [
                    ssga_actions(
                        distributions, "BIL", config["cutoff"], start=config["actions_from"]
                    ),
                    splits,
                ],
                ignore_index=True,
            )
        )
        for alternative in config.get("distribution_overrides", []):
            mask = actions.ex_date.eq(alternative["date"]) & actions.kind.eq("dividend")
            if mask.sum() != 1 or actions.loc[mask, "per_share"].iloc[0] != alternative["expected"]:
                raise ValueError("BIL distribution alternative changed")
            actions.loc[mask, "per_share"] = alternative["value"]
        actions = validate_actions(actions)
        calendar_audit = calendar_check(
            bars, pd.DatetimeIndex(json.loads(calendar.read_text())["sessions"])
        )
        if any(calendar_audit.values()):
            raise ValueError(f"BIL sessions not adjudicated: {calendar_audit}")
        bars.to_parquet(base / "bil_bars.parquet", compression="zstd")
        bars[["close"]].to_parquet(base / "bil_unconditional_features.parquet", compression="zstd")
        actions.to_parquet(base / "bil_actions.parquet", compression="zstd")
        parent_payloads = json.loads((parent / "payloads.json").read_text())
        if sha256_file(parent / "cohorts.json") != parent_payloads["cohorts.json"]:
            raise ValueError("parent cohort registration changed")
        shutil.copy2(parent / "cohorts.json", base / "cohorts.json")
        baseline_ids = {
            c["accounts"]["origin_pool_hold"]
            for c in json.loads((base / "cohorts.json").read_text())
            if c["asset"] in config["assets"] and c["years"] == 5
        }
        (base / "parent_baselines").mkdir()
        for key in sorted(baseline_ids):
            name = f"accounts/{key}/daily.parquet"
            if sha256_file(parent / name) != parent_payloads[name]:
                raise ValueError("parent stock baseline changed")
            shutil.copy2(parent / name, base / "parent_baselines" / f"{key}.parquet")
        source_hashes = {
            str(p.relative_to(data_root)): sha256_file(p)
            for p in (prices, distributions, calendar, proof, parent / "cohorts.json")
        }
        write_json(base / "source_hashes.json", source_hashes)
        registration = dict(
            registered_at=utc_now(),
            config=config,
            code=code_revision(),
            formal_accepted=False,
            inputs={
                str(p.relative_to(root)): sha256_file(p)
                for p in sorted(base.rglob("*"))
                if p.is_file()
            },
        )
    write_json(root / "registration.json", registration)
    # The reference cohorts are frozen in this run; never silently pick up a newer run.
    bars = pd.read_parquet(root / "inputs" / "bil_bars.parquet")
    jobs, comparisons = build_wait_jobs(root / "inputs", root, config, bars)
    write_json(root / "jobs.json", [{k: v for k, v in job.items() if k != "root"} for job in jobs])
    write_json(root / "comparisons.json", comparisons)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(execute_job, jobs, chunksize=1))
    write_json(root / "records.json", records)
    if any(row["status"] != "computed" for row in records):
        raise AssertionError("cash-account failures retained")
    by_id = {row["id"]: row for row in records}
    costs = Costs(**{k: dec(v) for k, v in config["execution"].items()})
    quotes = {}
    for key, row in by_id.items():
        last = pd.read_parquet(root / "accounts" / key / "daily.parquet").iloc[-1]
        quotes[key] = liquidation_quote(last, bars.close.loc[pd.Timestamp(row["end"])], costs)
    rows = []
    for comparison in comparisons:
        row = comparison.copy()
        if "id" in row:
            record = by_id[row["id"]]
            row.update(quotes[row["id"]])
            row.update(
                bil_annualized=record["annualized_return"],
                bil_xirr=record["xirr"],
                contributed=record["contributed"],
                gross_dividends=record["gross_dividends"],
                bil_max_drawdown=record["max_drawdown"],
            )
            baseline_path = (
                root / "inputs" / "parent_baselines" / f"{row['baseline_account']}.parquet"
            )
            baseline = pd.read_parquet(baseline_path)
            date = pd.Timestamp(row["end"])
            if date not in baseline.index:
                raise ValueError("cash comparison extends beyond paired stock account")
            row["stock_pool_wealth"] = float(baseline.loc[date, "equity"])
            row["gain_vs_zero_cash"] = row["wealth_net_liquidation"] - row["contributed"]
            row["gap_vs_stock_pool"] = row["wealth_net_liquidation"] - row["stock_pool_wealth"]
        rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(root / "all_waiting_results.csv", index=False)
    summary = dict(
        accounts=len(records),
        comparisons=len(rows),
        statuses=table.status.value_counts().to_dict(),
        prefix_exact=sum(bool(r.get("future_prefix_exact")) for r in records),
        formal_accepted=False,
    )
    write_json(root / "summary.json", summary)
    payloads = {
        str(p.relative_to(root)): sha256_file(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and p.name not in {"registration.json", "runtime.json", "payloads.json", "replay.json"}
    }
    write_json(root / "payloads.json", payloads)
    if replay:
        old = json.loads((replay / "payloads.json").read_text())
        changed = [
            name for name in sorted(set(old) | set(payloads)) if old.get(name) != payloads.get(name)
        ]
        write_json(
            root / "replay.json", dict(exact=not changed, files=len(payloads), changed=changed)
        )
        if changed:
            raise AssertionError("cash study replay differs")
    write_json(root / "runtime.json", dict(seconds=time.monotonic() - started, workers=workers))
    return summary
