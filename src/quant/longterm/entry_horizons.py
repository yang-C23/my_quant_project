"""Actual-fill calendar cohorts, paired controls and exact replayable cash accounts."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

import numpy as np
import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, utc_now, write_json
from quant.etl.restart import code_revision
from quant.longterm.action_audit import verify_action_ledger
from quant.longterm.cash_pool import PoolPolicy, capital_metrics, run_cash_pool
from quant.longterm.current_pe import current_pe_temperature
from quant.longterm.diagnostics import drawdown_episode, verify_price_ledger
from quant.longterm.engine import Strategy, performance, run_strategy
from quant.longterm.ledger import Costs, dec
from quant.longterm.pool_extensions import load_study_asset
from quant.longterm.research import save_result
from quant.longterm.stages import StageSpec, qualify_value_events, stage_features

_CACHE: dict = {}


def entry_rules(config: dict, asset: str) -> list[dict]:
    """Expand only registered mechanisms; no outcome-dependent selection."""
    rows = []

    def add(name, entry, expiry=20, lag=0, buy=0.4, drawdown=0.20, neighbor=False):
        rows.append(
            dict(
                id=name,
                entry=entry,
                expiry=expiry,
                lag=lag,
                buy=buy,
                drawdown=drawdown,
                scope="neighbor" if neighbor else "primary",
            )
        )

    add("unconditional", "unconditional")
    add("pressure", "pressure")
    for expiry in config["confirmation_windows"]:
        add(f"stabilized_{expiry}", "stabilized", expiry)
    if asset in config["valuation_assets"]:
        for lag in config["earnings_lag_months"]:
            add(f"valuation_lag{lag}", "valuation", lag=lag)
            add(f"value_pressure_lag{lag}", "value_pressure", lag=lag)
            for expiry in config["confirmation_windows"]:
                add(f"value_stabilized_{expiry}_lag{lag}", "value_stabilized", expiry, lag)
            for buy in config["valuation_neighbors"]["buy_thresholds"]:
                add(
                    f"value_stabilized_60_lag{lag}_buy{buy:g}",
                    "value_stabilized",
                    60,
                    lag,
                    buy,
                    neighbor=True,
                )
    if asset.startswith("dividend_lowvol"):
        for drawdown in config["dividend_lowvol_drawdown_neighbors"]:
            add(f"pressure_dd{drawdown:g}", "pressure", drawdown=drawdown, neighbor=True)
            for expiry in config["confirmation_windows"]:
                add(
                    f"stabilized_{expiry}_dd{drawdown:g}",
                    "stabilized",
                    expiry,
                    drawdown=drawdown,
                    neighbor=True,
                )
    return rows


def annual_origins(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Keep first eligible partial year as well as every later January cohort."""
    if len(index) < 254:
        return []
    eligible = index[252:]
    first = pd.Series(eligible, index=eligible).groupby(eligible.year).first().tolist()
    return [pd.Timestamp(date) for date in first]


def horizon_end(index: pd.DatetimeIndex, entry: pd.Timestamp | None, years: int):
    """A full calendar horizon cannot be inferred from 252 trading days/year."""
    if entry is None:
        return index[-1], "no_entry"
    target = entry + pd.DateOffset(years=years)
    i = index.searchsorted(target)
    return (index[i], "complete") if i < len(index) else (index[-1], "right_censored")


def first_fill(bars: pd.DataFrame, features: pd.DataFrame, policy: PoolPolicy, origin):
    """Find a candidate; the real ledger separately verifies its actual fill."""
    valid = pd.Series(True, index=bars.index)
    if policy.uses_value:
        valid &= features.temperature.notna() & features.temperature.lt(policy.buy_threshold)
    if policy.event_column:
        valid &= features[policy.event_column].fillna(False)
        if policy.uses_value:
            valid &= features.event_value_eligible.fillna(False)
    candidates = valid.shift(1, fill_value=False) & (bars.index >= origin)
    dates = bars.index[candidates]
    return dates[0] if len(dates) else None


def accumulated_cash(origin: pd.Timestamp, entry: pd.Timestamp, funding: dict) -> float:
    """All monthly contributions already arrived before a close-price entry."""
    months = (entry.year - origin.year) * 12 + entry.month - origin.month
    return funding["initial"] + funding["monthly"] * months


def _make_features(signals, rule, config, valuations):
    spec = StageSpec(
        **(config["stage"] | {"event_window": rule["expiry"], "drawdown": rule["drawdown"]})
    )
    features = stage_features(signals, spec)
    if rule["lag"]:
        features = features.assign(temperature=valuations[rule["lag"]].temperature)
        if rule["entry"].startswith("value_"):
            features = qualify_value_events(features, rule["buy"])
    return features


def prepare_inputs(data_root: Path, root: Path, config: dict) -> dict:
    """Save fixed input bytes and verify causal feature prefixes before accounts."""
    catalog = DataCatalog(data_root)
    parent = data_root / "research" / config["parent_run"]
    original_hashes = json.loads((parent / "payloads.json").read_text())
    coverage = {r["asset"]: r for r in json.loads((parent / "coverage.json").read_text())}
    observed = catalog.read("shiller_monthly", version=config["valuation_version"])
    root.joinpath("inputs").mkdir()
    observed.to_parquet(root / "inputs" / "valuation.parquet", compression="zstd")
    metadata, prefix_checks = {}, []
    for asset in config["assets"]:
        if asset == "sp500":
            raw = catalog.read("cboe_spx_close", version=config["spx_dataset_version"])
            raw["date"] = pd.to_datetime(raw.date)
            bars = raw.set_index("date")[["close"]].copy()
            signals, actions = bars.copy(), None
            evidence = dict(
                symbol="SP500",
                basis="price_index_no_dividends",
                lot="0.000001",
                source_version=config["spx_dataset_version"],
            )
        else:
            for path in (parent / "inputs").glob(f"{asset}*.parquet"):
                key = str(path.relative_to(parent))
                if sha256_file(path) != original_hashes[key]:
                    raise ValueError(f"parent input checksum changed: {key}")
            bars, signals, actions = load_study_asset(parent, asset)
            evidence = coverage[asset] | {"lot": "100" if actions is not None else "0.000001"}
            evidence["symbol"] = evidence.get("symbol", "NASDAQ100")
        bars, signals = bars.loc[: config["cutoff"]].copy(), signals.loc[: config["cutoff"]].copy()
        bars.to_parquet(root / "inputs" / f"{asset}_bars.parquet", compression="zstd")
        signals.to_parquet(root / "inputs" / f"{asset}_signals.parquet", compression="zstd")
        if actions is not None:
            actions.to_parquet(root / "inputs" / f"{asset}_actions.parquet", compression="zstd")
        evidence.update(
            first=str(bars.index[0].date()),
            last=str(bars.index[-1].date()),
            rows=len(bars),
            has_actions=actions is not None,
            formal_accepted=False,
        )
        metadata[asset] = evidence
        valuations, prior_valuations = {}, {}
        # A prefix ending 75 sessions earlier includes complete old crises while
        # removing future observations and any future monthly earnings releases.
        prefix = signals.iloc[:-75]
        if asset in config["valuation_assets"]:
            for lag in config["earnings_lag_months"]:
                valuations[lag], monthly = current_pe_temperature(
                    signals.close, observed, 10, lag, config["valuation_settings"]
                )
                monthly.to_parquet(
                    root / "inputs" / f"{asset}_pe_monthly_lag{lag}.parquet", compression="zstd"
                )
                past_observed = observed[pd.to_datetime(observed.date) <= prefix.index[-1]]
                prior_valuations[lag], _ = current_pe_temperature(
                    prefix.close, past_observed, 10, lag, config["valuation_settings"]
                )
        for rule in entry_rules(config, asset):
            features = _make_features(signals, rule, config, valuations)
            features.to_parquet(
                root / "inputs" / f"{asset}_{rule['id']}_features.parquet", compression="zstd"
            )
            earlier = _make_features(prefix, rule, config, prior_valuations)
            pd.testing.assert_frame_equal(features.loc[earlier.index], earlier, check_exact=True)
            prefix_checks.append(
                dict(asset=asset, rule=rule["id"], sessions=len(earlier), exact=True)
            )
    write_json(root / "coverage.json", metadata)
    write_json(root / "feature_prefix_checks.json", prefix_checks)
    return metadata


def _load(root: Path, asset: str, rule: str):
    key = str(root), asset, rule
    if key not in _CACHE:
        base = root / "inputs"
        bars = pd.read_parquet(base / f"{asset}_bars.parquet")
        path = base / f"{asset}_actions.parquet"
        actions = pd.read_parquet(path) if path.exists() else None
        features = pd.read_parquet(base / f"{asset}_{rule}_features.parquet")
        _CACHE[key] = bars, features, actions
    return _CACHE[key]


def build_jobs(root: Path, config: dict, metadata: dict) -> tuple[list[dict], list[dict]]:
    """Deduplicate identical control accounts without discarding any cohorts."""
    jobs, cohorts = {}, []

    def add(asset, rule, policy, start, end, engine="pool"):
        spec = dict(
            asset=asset,
            feature=rule,
            policy=policy,
            start=str(start.date()),
            end=str(end.date()),
            engine=engine,
            symbol=metadata[asset]["symbol"],
            lot=metadata[asset]["lot"],
            costs=config["execution"],
        )
        key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:20]
        jobs[key] = dict(spec, id=key, root=str(root))
        return key

    for asset in config["assets"]:
        bars, _, _ = _load(root, asset, "unconditional")
        for rule in entry_rules(config, asset):
            _, features, _ = _load(root, asset, rule["id"])
            base = asdict(
                PoolPolicy(
                    **config["funding"], entry=rule["entry"], exit="none", buy_threshold=rule["buy"]
                )
            )
            for origin in annual_origins(bars.index):
                candidate = first_fill(bars, features, PoolPolicy(**base), origin)
                # Verify actual affordable/pending fills in a short prefix. The
                # subsequent full reference must independently match this anchor.
                entry = None
                if candidate is not None:
                    end_idx = min(bars.index.searchsorted(candidate) + 25, len(bars) - 1)
                    if bars.index[end_idx] == candidate:
                        entry = candidate  # final-session fill checked by the full account
                    else:
                        discovery_policy = PoolPolicy(
                            **(
                                base
                                | {
                                    "initial": accumulated_cash(
                                        origin, candidate, config["funding"]
                                    )
                                }
                            )
                        )
                        discovery = run_cash_pool(
                            bars,
                            features,
                            discovery_policy,
                            symbol=metadata[asset]["symbol"],
                            start=candidate,
                            end=bars.index[end_idx],
                            lot=dec(metadata[asset]["lot"]),
                            costs=Costs(**{k: dec(v) for k, v in config["execution"].items()}),
                            actions=_load(root, asset, rule["id"])[2],
                            execution="next_close",
                        )
                        buys = discovery.journal[discovery.journal.kind.eq("buy")]
                        entry = pd.Timestamp(buys.date.min()) if len(buys) else None
                        if entry is None:
                            raise ValueError(
                                "candidate did not fill within 25 sessions; extend discovery explicitly"
                            )
                for years in config["horizons_years"]:
                    end, status = horizon_end(bars.index, entry, years)
                    if end <= origin:
                        continue
                    item = dict(
                        asset=asset,
                        rule=rule["id"],
                        scope=rule["scope"],
                        origin=str(origin.date()),
                        entry=str(entry.date()) if entry is not None else None,
                        years=years,
                        end=str(end.date()),
                        status=status,
                        wait_days=(entry - origin).days
                        if entry is not None
                        else (end - origin).days,
                        event_id=None,
                        accounts={},
                    )
                    if entry is not None:
                        signal_row = features.iloc[bars.index.get_loc(entry) - 1]
                        event = signal_row.get("event_id")
                        item["event_id"] = int(event) if pd.notna(event) else None
                    exits = config["value_exits"] if rule["lag"] else config["price_exits"]
                    if rule["entry"] == "unconditional":
                        exits = ["none"]
                    for exit_style in exits:
                        for core in config["core_fractions"]:
                            variant = f"{exit_style}_core{core:g}"
                            policy = base | dict(exit=exit_style, core_fraction=core)
                            item["accounts"][variant] = add(asset, rule["id"], policy, origin, end)
                    controls = {
                        "initial": config["funding"]["initial"],
                        "monthly": config["funding"]["monthly"],
                    }
                    item["accounts"]["origin_lump_hold"] = add(
                        asset,
                        "unconditional",
                        asdict(Strategy(name="lump_sum", **controls)),
                        origin,
                        end,
                        "legacy",
                    )
                    item["accounts"]["origin_pool_hold"] = add(
                        asset,
                        "unconditional",
                        asdict(PoolPolicy(entry="unconditional", exit="none", **config["funding"])),
                        origin,
                        end,
                    )
                    if entry is not None and end > entry:
                        controls["initial"] = accumulated_cash(origin, entry, config["funding"])
                        item["accounts"]["entry_lump_hold"] = add(
                            asset,
                            "unconditional",
                            asdict(Strategy(name="lump_sum", **controls)),
                            entry,
                            end,
                            "legacy",
                        )
                        item["accounts"]["entry_pool_hold"] = add(
                            asset,
                            "unconditional",
                            asdict(
                                PoolPolicy(
                                    entry="unconditional",
                                    exit="none",
                                    tranches=config["funding"]["tranches"],
                                    **controls,
                                )
                            ),
                            entry,
                            end,
                        )
                    cohorts.append(item)
    return list(jobs.values()), cohorts


def _execute(job: dict, *, shortened_end=None):
    bars, features, actions = _load(Path(job["root"]), job["asset"], job["feature"])
    costs = Costs(**{k: dec(v) for k, v in job["costs"].items()})
    arguments = dict(
        symbol=job["symbol"],
        start=job["start"],
        end=shortened_end or job["end"],
        costs=costs,
        lot=dec(job["lot"]),
        actions=actions,
        execution="next_close",
    )
    if shortened_end is not None:
        bars, features = bars.loc[:shortened_end], features.loc[:shortened_end]
        if actions is not None:
            # Future ex-dates are removed; payment after the prefix remains a
            # receivable and cannot become available cash early.
            actions = actions[pd.to_datetime(actions.ex_date) <= shortened_end]
            arguments["actions"] = actions
    result = (
        run_cash_pool(bars, features, PoolPolicy(**job["policy"]), **arguments)
        if job["engine"] == "pool"
        else run_strategy(bars, features, Strategy(**job["policy"]), **arguments)
    )
    result.metrics.update(capital_metrics(result.daily, result.journal))
    audit = (
        verify_price_ledger(result, bars.close)
        if actions is None
        else verify_action_ledger(result, bars.close, actions, costs)
    )
    if not audit["ok"]:
        raise AssertionError(f"independent account failed: {audit}")
    return result, audit


def execute_job(job: dict) -> dict:
    """Single account is chronological; worker exceptions are retained on disk."""
    target = Path(job["root"]) / "accounts" / job["id"]
    try:
        result, audit = _execute(job)
        save_result(result, target)
        write_json(target / "ledger_audit.json", audit)
        row = dict(id=job["id"], status="computed", **result.metrics)
        if job.get("prefix_check") and len(result.daily) > 100:
            cutoff = result.daily.index[-32]
            earlier, _ = _execute(job, shortened_end=cutoff)
            pd.testing.assert_frame_equal(
                result.daily.loc[:cutoff], earlier.daily, check_exact=True
            )
            expected = result.journal[pd.to_datetime(result.journal.date) <= cutoff].reset_index(
                drop=True
            )
            pd.testing.assert_frame_equal(
                expected, earlier.journal.reset_index(drop=True), check_exact=True
            )
            row["future_prefix_exact"] = True
        write_json(target / "record.json", row)
        return row
    except Exception as exc:
        target.mkdir(parents=True, exist_ok=True)
        (target / "error.txt").write_text(traceback.format_exc())
        row = dict(id=job["id"], status="error", reason=repr(exc))
        write_json(target / "record.json", row)
        return row


def loss_duration(daily: pd.DataFrame, contributions: pd.Series) -> dict:
    """Principal loss is measured against original cash supplied, even after entry."""
    below = daily.equity < contributions.reindex(daily.index) - 0.01
    first, longest = None, 0
    for date, lost in below.items():
        if lost and first is None:
            first = date
        if first is not None:
            longest = max(longest, (date - first).days)
            if not lost:
                first = None
    return dict(
        principal_loss_at_end=bool(below.iloc[-1]),
        maximum_principal_loss=float((daily.equity / contributions.reindex(daily.index) - 1).min()),
        longest_principal_loss_days=longest,
        principal_recovery_censored=first is not None,
    )


def post_entry_metrics(daily: pd.DataFrame, journal: pd.DataFrame, entry) -> dict:
    """Measurement reset only, not a fabricated ledger or additional contribution."""
    original_contributions = daily.external_flow.cumsum()
    part = daily.loc[entry:].copy()
    if len(part) < 2:
        return {}
    prior = daily.loc[daily.index < pd.Timestamp(entry)]
    first = part.index[0]
    part.loc[first, "external_flow"] += part.loc[first, "pre_flow_equity"]
    part.loc[first, "pre_flow_equity"] = 0
    for name in ("commission", "slippage", "gross_dividends", "dividend_tax", "turnover_notional"):
        if len(prior):
            part[name] -= prior[name].iloc[-1]
    trades = journal[pd.to_datetime(journal.date) >= pd.Timestamp(entry)]
    metrics = performance(part, trades)
    episode = drawdown_episode(part.twr_nav)
    metrics.update(loss_duration(daily.loc[entry:], original_contributions))
    metrics.update(
        recovery_days=episode["peak_to_recovery_days"],
        peak_recovery_censored=episode["unrecovered"],
    )
    return {"post_" + k: v for k, v in metrics.items()}


def analyze(root: Path, cohorts: list[dict], records: list[dict], config: dict) -> dict:
    """All rows, paired wealth gaps, no-entry and incomplete horizons stay visible."""
    by_id = {row["id"]: row for row in records}
    rows, waits = [], []
    cached = {}

    def account(key):
        if key not in cached:
            p = root / "accounts" / key
            cached[key] = (
                pd.read_parquet(p / "daily.parquet"),
                pd.read_parquet(p / "journal.parquet"),
            )
        return cached[key]

    for cohort in cohorts:
        cached.clear()  # bound analysis memory; no global collection of daily histories
        comparison = cohort["accounts"]
        primary = by_id[comparison["none_core0"]]
        if primary["status"] != "computed":
            continue
        actual = primary["first_tactical_buy"]
        if actual != cohort["entry"]:
            raise AssertionError(f"reference first fill changed: {actual}, {cohort}")
        wealth = {name: by_id[key]["ending_wealth"] for name, key in comparison.items()}
        contributed = {by_id[key]["contributed"] for key in comparison.values()}
        if len(contributed) != 1:
            raise AssertionError(f"paired account funding differs: {cohort}")
        for variant, key in comparison.items():
            record = by_id[key]
            row = {k: v for k, v in cohort.items() if k != "accounts"} | dict(
                variant=variant, account=key
            )
            row.update(record)
            # Preserve the cohort's completeness separately from account success.
            row["status"] = cohort["status"]
            row["wealth_gap_vs_origin_pool"] = record["ending_wealth"] - wealth["origin_pool_hold"]
            row["wealth_gap_vs_origin_lump"] = record["ending_wealth"] - wealth["origin_lump_hold"]
            row["wealth_gap_vs_no_exit"] = record["ending_wealth"] - wealth["none_core0"]
            row["wealth_gap_vs_entry_pool"] = record["ending_wealth"] - wealth.get(
                "entry_pool_hold", np.nan
            )
            row["ending_principal_loss"] = record["ending_wealth"] < record["contributed"] - 0.01
            d, j = account(key)
            if cohort["entry"]:
                row.update(post_entry_metrics(d, j, cohort["entry"]))
            rows.append(row)
        # One waiting report per origin/entry, not twice for 5 and 10 years.
        if cohort["years"] == config["horizons_years"][0]:
            d, _ = account(comparison["none_core0"])
            baseline, _ = account(comparison["origin_pool_hold"])
            for months in config["waiting_months"]:
                target = pd.Timestamp(cohort["origin"]) + pd.DateOffset(months=months)
                available = d.index[d.index >= target]
                wait = {
                    k: cohort[k] for k in ("asset", "rule", "scope", "origin", "entry", "wait_days")
                }
                wait.update(months=months, observation_available=bool(len(available)))
                if len(available):
                    date = available[0]
                    wait.update(
                        date=str(date.date()),
                        still_waiting=not cohort["entry"] or pd.Timestamp(cohort["entry"]) > date,
                        wealth_gap_vs_origin_pool=float(
                            d.loc[date, "equity"] - baseline.loc[date, "equity"]
                        ),
                    )
                waits.append(wait)
    table = pd.DataFrame(rows)
    table.to_csv(root / "all_cohort_results.csv", index=False)
    pd.DataFrame(waits).to_csv(root / "waiting_all.csv", index=False)
    groups = ["asset", "rule", "scope", "variant", "years"]
    summaries = []
    for keys, group in table.groupby(groups, sort=True):
        full = group[group.status.eq("complete")]
        row = dict(zip(groups, keys, strict=True))
        row.update(
            cohorts=len(group),
            complete=len(full),
            right_censored=int(group.status.eq("right_censored").sum()),
            no_entry=int(group.status.eq("no_entry").sum()),
            unique_complete_entries=full.entry.nunique(),
            median_wait_days=float(group.wait_days.median()),
        )
        if len(full):
            for name in (
                "post_annualized_return",
                "post_xirr",
                "post_max_drawdown",
                "post_maximum_principal_loss",
                "post_longest_principal_loss_days",
                "wealth_gap_vs_origin_pool",
                "wealth_gap_vs_entry_pool",
                "wealth_gap_vs_no_exit",
            ):
                row[f"median_{name}"] = float(full[name].median())
                row[f"worst_{name}"] = float(
                    full[name].min() if "days" not in name else full[name].max()
                )
            row.update(
                ending_principal_loss_count=int(full.ending_principal_loss.sum()),
                wealth_beats_origin_pool_count=int(full.wealth_gap_vs_origin_pool.gt(0.01).sum()),
            )
            clustered = full.groupby("entry").post_annualized_return.median()
            row["entry_date_balanced_median_post_annualized_return"] = float(clustered.median())
        summaries.append(row)
    pd.DataFrame(summaries).to_csv(root / "summary.csv", index=False)
    result = dict(
        accounts=len(records),
        cohorts=len(cohorts),
        comparison_rows=len(table),
        account_statuses=pd.Series([r["status"] for r in records]).value_counts().to_dict(),
        cohort_statuses=pd.Series([r["status"] for r in cohorts]).value_counts().to_dict(),
        account_future_prefix_checks=sum(bool(r.get("future_prefix_exact")) for r in records),
        formal_accepted=False,
    )
    write_json(root / "summary.json", result)
    return result


def run_study(
    data_root: Path,
    root: Path,
    config_path: Path,
    workers: int,
    *,
    replay: Path | None = None,
    pilot: int = 0,
) -> dict:
    """A new output directory is mandatory; frozen inputs may be replayed exactly."""
    if root.exists() or workers < 1:
        raise ValueError("new directory and positive worker count required")
    if workers > int(os.getenv("QUANT_WORKERS", workers)):
        raise ValueError("workers exceed admitted shared budget")
    started = time.monotonic()
    config = json.loads(config_path.read_text())
    root.mkdir(parents=True)
    if replay:
        import shutil

        original = json.loads((replay / "registration.json").read_text())
        if (
            original["config"] != config
            or original["code"]["sources"] != code_revision()["sources"]
        ):
            raise ValueError("replay code/config differs from registration")
        for name, digest in original["input_hashes"].items():
            if sha256_file(replay / name) != digest:
                raise ValueError(f"replay input changed: {name}")
        shutil.copytree(replay / "inputs", root / "inputs")
        for name in ("coverage.json", "feature_prefix_checks.json"):
            shutil.copy2(replay / name, root / name)
        metadata = json.loads((root / "coverage.json").read_text())
        registration = original
    else:
        metadata = prepare_inputs(data_root, root, config)
        registration = dict(
            registered_at=utc_now(),
            config=config,
            code=code_revision(),
            config_sha256=sha256_file(config_path),
            formal_accepted=False,
            input_hashes={
                str(p.relative_to(root)): sha256_file(p)
                for p in sorted((root / "inputs").glob("*.parquet"))
            },
        )
    write_json(root / "registration.json", registration)
    jobs, cohorts = build_jobs(root, config, metadata)
    # Check representative real prefixes across every engine/entry/exit/core.
    checked = set()
    for job in jobs:
        key = (
            job["asset"],
            job["engine"],
            job["policy"].get("entry"),
            job["policy"].get("exit"),
            job["policy"].get("core_fraction"),
        )
        job["prefix_check"] = key not in checked
        checked.add(key)
    if pilot:
        jobs = jobs[:pilot]
    write_json(root / "jobs.json", [{k: v for k, v in j.items() if k != "root"} for j in jobs])
    write_json(root / "cohorts.json", cohorts)
    print(
        json.dumps(
            dict(event="registered", accounts=len(jobs), cohorts=len(cohorts), workers=workers)
        ),
        flush=True,
    )
    records = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(execute_job, jobs, chunksize=1):
            records.append(row)
            if len(records) % 100 == 0:
                print(
                    json.dumps(
                        dict(
                            event="progress",
                            completed=len(records),
                            errors=sum(r["status"] == "error" for r in records),
                        )
                    ),
                    flush=True,
                )
    write_json(root / "account_records.json", records)
    if any(r["status"] != "computed" for r in records):
        raise AssertionError("account failures retained; analysis stopped")
    result = dict(pilot_accounts=len(records)) if pilot else analyze(root, cohorts, records, config)
    payloads = {
        str(p.relative_to(root)): sha256_file(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and p.name not in {"registration.json", "runtime.json", "payloads.json", "replay.json"}
    }
    write_json(root / "payloads.json", payloads)
    if replay:
        previous = json.loads((replay / "payloads.json").read_text())
        changed = sorted(
            k for k in set(previous) | set(payloads) if previous.get(k) != payloads.get(k)
        )
        write_json(
            root / "replay.json", dict(exact=not changed, files=len(payloads), changed=changed)
        )
        if changed:
            raise AssertionError(f"replay differences: {changed[:10]}")
    write_json(
        root / "runtime.json",
        dict(seconds=time.monotonic() - started, workers=workers, pid=os.getpid()),
    )
    return result
