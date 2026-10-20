"""Cash-pool study: immutable inputs, all experiments, paired controls and replay."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
import json
import logging
from pathlib import Path
import traceback

import pandas as pd

from quant.config import Settings, load_config
from quant.data.catalog import DataCatalog
from quant.data.snapshots import SnapshotStore, sha256_file, utc_now, write_json
from quant.etl.restart import code_revision
from quant.longterm.action_audit import verify_action_ledger
from quant.longterm.asset_inputs import prepare_action_prices
from quant.longterm.cash_pool import FACTOR_COLUMNS, PoolPolicy, capital_metrics, run_cash_pool
from quant.longterm.diagnostics import drawdown_episode, verify_price_ledger
from quant.longterm.engine import Backtest, Strategy, run_strategy
from quant.longterm.ledger import Costs, dec
from quant.longterm.pool_data import shiller_temperature, supplemental_features
from quant.longterm.pool_registry import pool_registry, pool_windows
from quant.longterm.research import _load_asset, save_result, valuation_features
from quant.longterm.stages import StageSpec, event_study, qualify_value_events, stage_features

logger = logging.getLogger(__name__)


def _paired_metrics(result: Backtest, control: Backtest) -> dict:
    """Identical funding/dates/costs/core; waiting wealth gaps include all idle cash."""
    if not result.daily.index.equals(control.daily.index):
        raise ValueError("paired comparison requires identical sessions")
    if not result.daily.external_flow.equals(control.daily.external_flow):
        raise ValueError("paired comparison requires identical external contributions")
    out = {}
    for key in ("ending_wealth", "annualized_return", "max_drawdown", "xirr"):
        a, b = result.metrics[key], control.metrics[key]
        out[f"delta_{key}_vs_pool"] = a - b if a is not None and b is not None else None
    out["control_ending_wealth"] = control.metrics["ending_wealth"]
    out["control_annualized_return"] = control.metrics["annualized_return"]
    out["control_max_drawdown"] = control.metrics["max_drawdown"]
    for months in (6, 12, 24):
        after = result.daily.loc[result.daily.index[0] + pd.DateOffset(months=months) :]
        date = after.index[0] if len(after) else None
        out[f"wealth_gap_at_{months}m_vs_pool"] = (
            float(result.daily.at[date, "equity"] - control.daily.at[date, "equity"])
            if date is not None
            else None
        )
    return out


def _run_asset(job: dict) -> dict:
    """One process owns an asset directory; completed cases are restartable."""
    root = Path(job["directory"])
    registration = json.loads((root / "registration.json").read_text())
    config, versions = registration["config"], registration["catalog_versions"]
    asset, evidence = job["asset"], job["evidence"]
    directory = root / asset["id"]
    directory.mkdir(exist_ok=True)
    bars = pd.read_parquet(root / "inputs" / f"{asset['id']}.parquet")
    catalog = DataCatalog(Path(job["data_root"]))
    features_input = bars.copy()
    actions = None
    if job.get("actions"):
        actions = pd.read_parquet(root / "inputs" / f"{asset['id']}_actions.parquet")
        bars, features_input, mark_corrections = prepare_action_prices(bars, actions)
        mark_corrections.to_parquet(directory / "mark_corrections.parquet", compression="zstd")
        bars.to_parquet(directory / "execution_marks.parquet", compression="zstd")
    supplemental, supplemental_evidence = supplemental_features(
        bars, asset, catalog, versions, config
    )
    supplemental.to_parquet(directory / "supplemental.parquet", compression="zstd")
    write_json(directory / "supplemental_evidence.json", supplemental_evidence)
    supplemental_cache = {"{}": supplemental}
    primary_spec = StageSpec(**config["stages"])
    primary_features = stage_features(features_input, primary_spec, supplemental=supplemental)
    primary_features.to_parquet(directory / "stages.parquet", compression="zstd")
    events = event_study(
        features_input,
        primary_features,
        forward_sessions=tuple(config["validation"]["event_horizons_sessions"]),
    )
    events.to_parquet(directory / "events.parquet", compression="zstd")
    feature_cache = {json.dumps(asdict(primary_spec), sort_keys=True): primary_features}
    value_cache: dict[tuple, pd.Series | str] = {}
    controls = {}
    rows = []
    experiments = registration["experiments"]
    defaults = config["execution"]
    symbol = evidence.get("symbol", asset["index"])
    is_etf = asset.get("style") == "dividend_lowvol" or asset.get("instrument_kind") == "ETF"
    lot = dec(100 if is_etf and asset["market"] == "CN" else 1 if is_etf else 0.000001)
    for number, experiment in enumerate(experiments):
        if experiment.get("assets") and asset["id"] not in experiment["assets"]:
            continue
        identifier = experiment["id"]
        common = {
            "asset": asset["id"],
            "asset_name": asset["name"],
            "experiment": identifier,
            "basis": evidence["basis"],
            "evidence_grade": "exploratory",
            "formal_accepted": False,
            "policy_json": json.dumps(experiment["policy"], sort_keys=True),
            "valuation_source": experiment.get("valuation_source", "official_required"),
        }
        if (
            experiment.get("engine") == "legacy"
            and "kdj" in experiment["legacy"]
            and not {"high", "low"}.issubset(bars)
        ):
            rows.append(common | {"status": "blocked", "reason": "actual_OHLC_missing"})
            continue
        policy = PoolPolicy(**experiment["policy"])
        if policy.entry.endswith("kdj") and not {"high", "low"}.issubset(bars):
            rows.append(common | {"status": "blocked", "reason": "actual_OHLC_missing"})
            continue
        key = json.dumps(experiment["stages"], sort_keys=True)
        delay = experiment.get("availability_delay", 0)
        key += f":delay{delay}" if delay else ""
        lags = experiment.get("supplemental_lags", {})
        lag_key = json.dumps(lags, sort_keys=True)
        if lag_key not in supplemental_cache:
            lagged, lag_evidence = supplemental_features(
                bars, asset, catalog, versions, config, **lags
            )
            supplemental_cache[lag_key] = lagged
            lagged.to_parquet(directory / f"supplemental_{identifier}.parquet", compression="zstd")
            write_json(directory / f"supplemental_{identifier}.json", lag_evidence)
        if lags:
            key += lag_key
        if key not in feature_cache:
            feature_cache[key] = stage_features(
                features_input,
                StageSpec(**experiment["stages"]),
                supplemental=supplemental_cache[lag_key].shift(delay),
            )
        features = feature_cache[key]
        eligible = pd.Series(True, index=bars.index)
        if job.get("research_start"):
            eligible &= bars.index >= pd.Timestamp(job["research_start"])
        factor = policy.event_column
        columns = FACTOR_COLUMNS.get(factor, [])
        if columns:
            if (
                not set(columns).issubset(features)
                or not features[columns].notna().all(axis=1).any()
            ):
                rows.append(
                    common | {"status": "blocked", "reason": "supplemental_factor_unavailable"}
                )
                continue
            eligible &= features[columns].notna().all(axis=1)
        if experiment.get("metric"):
            value_key = (
                experiment.get("valuation_source", "official"),
                experiment["metric"],
                experiment["window"],
                experiment.get("observation_lag_months", 0),
            )
            if value_key not in value_cache:
                try:
                    if value_key[0] == "shiller_proxy":
                        value = shiller_temperature(
                            bars,
                            catalog.read("shiller_monthly", version=versions["shiller_monthly"]),
                            value_key[1],
                            value_key[2],
                            value_key[3],
                            config,
                        )
                    else:
                        value = valuation_features(
                            asset, bars, catalog, versions, value_key[1], value_key[2]
                        )
                    value_cache[value_key] = (
                        value if value.notna().any() else "no_valid_valuation_after_warmup"
                    )
                except (ValueError, KeyError, FileNotFoundError) as exc:
                    value_cache[value_key] = str(exc)
            value = value_cache[value_key]
            if isinstance(value, str):
                rows.append(common | {"status": "blocked", "reason": value})
                continue
            features = features.assign(temperature=value)
            if policy.uses_value and policy.event_column:
                features = qualify_value_events(features, policy.buy_threshold)
            eligible &= value.notna()
        allowed = bars.index[eligible]
        windows = pool_windows(allowed, config, calendar=bars.index)
        if not windows:
            rows.append(
                common | {"status": "blocked", "reason": "insufficient_common_factor_history"}
            )
            continue
        cost_values = defaults | experiment.get("execution_override", {})
        costs = Costs(
            commission_rate=dec(cost_values["commission_rate"]),
            minimum_commission=dec(cost_values["minimum_commission"]),
            slippage_bps=dec(cost_values["slippage_bps"]),
        )
        for window in windows:
            if (
                experiment["scope"] == "neighbor"
                and window["id"] not in config["validation"]["neighbor_windows"]
            ):
                continue
            case = directory / identifier / window["id"]
            record_file = case / "record.json"
            if record_file.exists():
                rows.append(json.loads(record_file.read_text()))
                continue
            record = common | {"window": window["id"], "phase": window["phase"]}
            try:
                arguments = dict(
                    symbol=symbol,
                    start=window["start"],
                    end=window["end"],
                    costs=costs,
                    lot=lot,
                    actions=actions,
                    price_basis="raw",
                    execution="next_close",
                )
                if experiment["engine"] == "legacy":
                    name = experiment["legacy"]
                    legacy = Strategy(
                        name="kdj" if name == "kdj_core50" else name,
                        core_fraction=0.5 if name == "kdj_core50" else 0,
                        **config["funding"],
                    )
                    result = run_strategy(bars, features, legacy, **arguments)
                    result.metrics.update(capital_metrics(result.daily, result.journal))
                    control_policy = replace(
                        policy,
                        entry="unconditional",
                        core_fraction=legacy.core_fraction,
                        exit="none",
                    )
                else:
                    result = run_cash_pool(bars, features, policy, **arguments)
                    control_policy = replace(
                        policy,
                        entry="unconditional",
                        exit="none",
                        event_tranches=0,
                        dynamic_deep_threshold=None,
                    )
                control_key = (
                    window["start"],
                    window["end"],
                    json.dumps(asdict(control_policy), sort_keys=True),
                    json.dumps(asdict(costs), sort_keys=True, default=str),
                )
                if control_key not in controls:
                    controls[control_key] = run_cash_pool(
                        bars, features, control_policy, **arguments
                    )
                control = controls[control_key]
                # Independent reconstruction covers every price-only case, including
                # sales and core sleeves, not just the strategy which looks best.
                audit = (
                    verify_price_ledger(result, bars.close)
                    if actions is None
                    else verify_action_ledger(result, bars.close, actions, costs)
                )
                save_result(result, case)
                write_json(case / "ledger_audit.json", audit)
                episode = drawdown_episode(result.daily.twr_nav)
                record.update(
                    status="computed",
                    **result.metrics,
                    **_paired_metrics(result, control),
                    drawdown_peak=episode["peak_date"],
                    drawdown_trough=episode["trough_date"],
                    drawdown_recovery=episode["recovery_date"],
                    worst_drawdown_recovery_days=episode["peak_to_recovery_days"],
                    drawdown_unrecovered=episode["unrecovered"],
                    independent_ledger_verified=audit["ok"],
                    result_directory=str(case.relative_to(root)),
                )
            except Exception as exc:
                record.update(status="error", reason=repr(exc))
                case.mkdir(parents=True, exist_ok=True)
                (case / "error.txt").write_text(traceback.format_exc())
            write_json(record_file, record)
            rows.append(record)
        if number % 10 == 0:
            write_json(
                directory / "progress.json",
                {"experiment": identifier, "completed_records": len(rows), "updated_at": utc_now()},
            )
    table = pd.DataFrame(rows)
    table.to_parquet(directory / "results.parquet", compression="zstd")
    return {
        "asset": asset["id"],
        "records": len(rows),
        "statuses": table.status.value_counts().to_dict(),
    }


def run_pool_research(
    settings: Settings,
    config_path: Path,
    reference_run: Path,
    *,
    workers: int = 2,
    replay_run: Path | None = None,
    resume_run: Path | None = None,
) -> dict:
    """Freeze before scoring; use only pinned input versions and retain every failure."""
    if not 1 <= workers <= 8 or (replay_run and resume_run):
        raise ValueError("use one to eight workers and only one replay/resume mode")
    config = load_config(config_path)
    reference = json.loads((reference_run / "registration.json").read_text())
    universe = reference["config"]["universe"] + config.get("additional_assets", [])
    catalog, store = DataCatalog(settings.data_root), SnapshotStore(settings.data_root)
    snapshot_id = reference["snapshot_id"]
    if not store.verify(snapshot_id)["ok"]:
        raise ValueError("reference snapshot checksum failure")
    code = code_revision()
    lock = Path(__file__).resolve().parents[3] / "requirements-lock.txt"
    pinned = {m["dataset"]: m["version"] for m in catalog.list_datasets()}
    # Retain the original price and VIX vintages; only additive datasets are new.
    pinned.update(
        {
            name: version
            for name, version in reference["catalog_versions"].items()
            if not name.startswith(("cffex_", "cftc_"))
        }
    )
    registration = {
        "registered_at": utc_now(),
        "config": config,
        "config_sha256": sha256_file(config_path),
        "code": code,
        "dependency_lock_sha256": sha256_file(lock),
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": sha256_file(store.path(snapshot_id) / "manifest.json"),
        "catalog_versions": pinned,
        "reference_run": str(reference_run.resolve()),
        "universe": universe,
        "experiments": pool_registry(config),
        "retrospective_seen_history": True,
        "selection": "none",
    }
    prior = replay_run or resume_run
    if prior:
        original = json.loads((prior / "registration.json").read_text())
        for key in (
            "config",
            "dependency_lock_sha256",
            "snapshot_id",
            "snapshot_manifest_sha256",
            "experiments",
        ):
            if original[key] != registration[key]:
                raise ValueError(f"replay/resume mismatch: {key}")
        if original["code"]["sources"] != code["sources"]:
            raise ValueError("replay/resume requires identical source bytes")
        registration = original
        pinned = original["catalog_versions"]
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%fZ")
    directory = resume_run or settings.data_root / "research" / ("cash-pool-" + stamp)
    directory.mkdir(parents=True, exist_ok=bool(resume_run))
    (directory / "inputs").mkdir(exist_ok=True)
    if not resume_run:
        write_json(directory / "registration.json", registration)
    jobs, coverage, unavailable = [], [], []
    for asset in universe:
        name = asset["id"]
        try:
            bars, evidence = _load_asset(settings, asset, catalog, pinned, snapshot_id=snapshot_id)
            release = reference["config"].get("index_release_dates", {}).get(name)
            if release:
                bars = bars.loc[release:]
            if bars.empty:
                raise ValueError("no post-publication history")
            action_dataset = None
            warmup = config["validation"]["initial_price_warmup"]
            if len(bars) <= warmup:
                raise ValueError("insufficient_prior_price_warmup_for_matched_comparison")
            research_start = str(bars.index[warmup].date())
            if "ETF" in evidence["basis"]:
                action_dataset = config["corporate_action_sources"].get(name)
                if not action_dataset or action_dataset not in pinned:
                    raise ValueError("complete_company_actions_and_payment_dates_not_yet_admitted")
                action_manifest = catalog.manifest(action_dataset, pinned[action_dataset])
                metadata = action_manifest["metadata"]
                if (
                    not metadata.get("complete_within_reviewed_scope")
                    or pd.Timestamp(metadata["coverage_end"]) < bars.index[-1]
                    or pd.Timestamp(metadata["coverage_start"]) > bars.index[0]
                ):
                    raise ValueError("company_action_review_does_not_cover_price_history")
                actions = catalog.read(action_dataset, version=pinned[action_dataset])
                # Pre-listing actions cannot create holdings, and may not be
                # applied again to a post-listing execution-price series.
                actions = actions[pd.to_datetime(actions.ex_date) >= bars.index[0]]
                actions.to_parquet(
                    directory / "inputs" / f"{name}_actions.parquet", compression="zstd"
                )
                if len(bars) < 61:
                    raise ValueError("ETF has fewer than 60 prior listed sessions")
                research_start = str(bars.index[max(60, warmup)].date())
                evidence.update(
                    basis="ETF_actual_price_with_reviewed_company_actions",
                    corporate_actions_dataset=action_dataset,
                    corporate_actions_version=pinned[action_dataset],
                    limitations=[
                        "named_surviving_product_case_study_not_historical_selection",
                        "retention_and_PIT_review_pending",
                        "close_execution_and_cost_assumptions",
                    ],
                )
            bars.to_parquet(directory / "inputs" / f"{name}.parquet", compression="zstd")
            coverage.append(
                {
                    "asset": name,
                    "first_date": str(bars.index[0].date()),
                    "last_date": str(bars.index[-1].date()),
                    "rows": len(bars),
                    "funding_start_after_shared_warmup": research_start,
                    "prior_price_observations": warmup,
                    **evidence,
                }
            )
            jobs.append(
                {
                    "directory": str(directory),
                    "data_root": str(settings.data_root),
                    "asset": asset,
                    "evidence": evidence,
                    "actions": action_dataset,
                    "research_start": research_start,
                }
            )
        except (ValueError, FileNotFoundError) as exc:
            coverage.append({"asset": name, "status": "blocked", "reason": str(exc)})
            unavailable.extend(
                {"asset": name, "experiment": e["id"], "status": "blocked", "reason": str(exc)}
                for e in registration["experiments"]
                if not e.get("assets") or name in e["assets"]
            )
    write_json(directory / "coverage.json", coverage)
    outcomes = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_asset, job): job["asset"]["id"] for job in jobs}
        for future in as_completed(futures):
            name = futures[future]
            try:
                outcome = future.result()
                outcomes.append(outcome)
                logger.info("%s: %s", name, outcome["statuses"])
            except Exception as exc:
                outcome = {"asset": name, "status": "asset_error", "reason": repr(exc)}
                outcomes.append(outcome)
                logger.exception("asset failed: %s", name)
            write_json(directory / "progress.json", {"updated_at": utc_now(), "outcomes": outcomes})
    tables = [
        pd.read_parquet(directory / job["asset"]["id"] / "results.parquet")
        for job in jobs
        if (directory / job["asset"]["id"] / "results.parquet").exists()
    ]
    table = pd.concat([*tables, pd.DataFrame(unavailable)], ignore_index=True)
    table.to_parquet(directory / "results.parquet", compression="zstd")
    table.to_csv(directory / "results.csv", index=False)
    summary = {
        "directory": str(directory),
        "experiments": len(registration["experiments"]),
        "records": len(table),
        "statuses": table.status.value_counts().to_dict(),
        "outcomes": outcomes,
        "selection": "none",
        "formal_accepted": False,
    }
    make_pool_report(directory, table, coverage, summary)
    write_json(directory / "summary.json", summary)
    excluded = {
        "registration.json",
        "progress.json",
        "summary.json",
        "payloads.json",
        "replay.json",
    }
    payloads = {
        str(path.relative_to(directory)): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name not in excluded and path.suffix != ".txt"
    }
    write_json(directory / "payloads.json", payloads)
    if replay_run:
        previous = json.loads((replay_run / "payloads.json").read_text())
        changed = sorted(
            key for key in set(previous) | set(payloads) if previous.get(key) != payloads.get(key)
        )
        replay = {
            "identical": not changed,
            "changed_files": changed,
            "payload_count": len(payloads),
        }
        write_json(directory / "replay.json", replay)
        summary["replay"] = replay
    return summary


def make_pool_report(directory: Path, table: pd.DataFrame, coverage: list, summary: dict) -> None:
    """A complete CSV accompanies a readable report; no winner-only filtering."""
    successful = table[table.status.eq("computed")]
    text = [
        "# 现金池与压力阶段研究",
        "",
        "这是回溯性探索，不是正式准入或未见样本外证明。全部实验见 results.csv。",
        "价格指数不含分红、汇率及QDII折溢价；月供不是收益。所有等待期间现金均计入账户。",
        "Shiller条目是带明确滞后假设的修订版月度代理，不能当作当年真实可获得的PE。",
        "",
        f"登记 {summary['experiments']} 项规则；状态计数：{summary['statuses']}。",
        "",
        "## 数据覆盖",
        "",
        pd.DataFrame(coverage)
        .drop(columns=["limitations"], errors="ignore")
        .to_markdown(index=False),
        "",
        "## 同窗口核心结果",
        "",
    ]
    if not successful.empty:
        names = [
            "legacy_lump_sum",
            "legacy_dca",
            "pool_unconditional_core0",
            "pool_pressure_core0",
            "pool_stabilized_core0",
            "pool_relief_core0",
            "pool_vix_relief_core0",
            "pool_margin_relief_core0",
            "pool_position_relief_core0",
            "pool_stabilized_core0.5",
        ]
        selected = successful[
            successful.experiment.isin(names)
            & successful.window.isin(["latest_5y", "latest_10y", "common_since_2016"])
        ]
        columns = [
            "asset",
            "experiment",
            "window",
            "start",
            "end",
            "annualized_return",
            "xirr",
            "max_drawdown",
            "ending_wealth",
            "average_cash_fraction",
            "initial_wait_days",
            "longest_capital_shortfall_days",
            "delta_ending_wealth_vs_pool",
        ]
        text += [selected[columns].to_markdown(index=False), "", "## 全部滚动窗口", ""]
        rolling = successful[successful.window.str.startswith(("latest_", "rolling_"))]
        if len(rolling):
            rolling = rolling.copy()
            rolling["horizon_years"] = rolling.window.str.extract(r"_(\d+)y", expand=False).astype(
                int
            )
            grouped = rolling.groupby(["asset", "experiment", "horizon_years"], sort=True).agg(
                windows=("ending_wealth", "size"),
                worst_annualized=("annualized_return", "min"),
                median_annualized=("annualized_return", "median"),
                worst_drawdown=("max_drawdown", "min"),
                loss_window_fraction=("ending_profit", lambda x: float((x < 0).mean())),
                median_wait_days=("initial_wait_days", "median"),
            )
            grouped.to_csv(directory / "rolling_summary.csv")
            text += [
                "所有规则的最差/中位窗口及亏损窗口比例保存在 rolling_summary.csv。",
                "重叠窗口与同期市场并不独立；这些比例不是可外推的独立胜率。",
            ]
    missing = table[~table.status.eq("computed")]
    text += [
        "",
        "## 暂停与错误",
        "",
        missing.groupby(["status", "reason"], dropna=False)
        .size()
        .rename("records")
        .reset_index()
        .to_markdown(index=False)
        if len(missing)
        else "本数据子集没有暂停记录；不代表其他数据已获准入。",
        "",
        "未通过公司行动、许可和历史发布时间验收的产品保留暂停记录。没有自动实盘交易。",
    ]
    (directory / "report.md").write_text("\n".join(text) + "\n", encoding="utf-8")
