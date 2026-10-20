"""Frozen experiments, pinned inputs, blocked-evidence rows and reproducible reports."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant.config import Settings, load_config
from quant.data.catalog import DataCatalog
from quant.data.snapshots import SnapshotStore, sha256_file, utc_now, write_json
from quant.etl.restart import code_revision
from quant.longterm.allocation import run_allocation
from quant.longterm.engine import Backtest, Strategy, run_strategy
from quant.longterm.features import align_available, price_features, valuation_temperature
from quant.longterm.ledger import Costs, dec

logger = logging.getLogger(__name__)


def experiment_registry(config: dict) -> list[dict]:
    """Register primary, alternative and sensitivity hypotheses before any scoring."""
    experiments = [
        {"id": "lump_sum", "name": "lump_sum", "core_fraction": 0},
        {"id": "dca", "name": "dca", "core_fraction": 0},
        {"id": "kdj", "name": "kdj", "core_fraction": 0},
        {"id": "kdj_core50", "name": "kdj", "core_fraction": 0.5},
    ]
    matrix = config["strategy_matrix"]
    for metric in matrix["valuation_metrics"]:
        for window in matrix["percentile_windows"]:
            for exit_style in matrix["exits"]:
                for core in matrix["core_fractions"]:
                    for name in ("valuation", "panic", "stabilized", "value_kdj"):
                        # Alternative metrics/windows are single-factor ablations of primary rules.
                        if name != "valuation" and (metric != "pe" or window != 10):
                            continue
                        experiments.append(
                            {
                                "id": f"{name}_{metric}_{window}_{exit_style}_core{core:g}",
                                "name": name,
                                "metric": metric,
                                "window": window,
                                "exit_style": exit_style,
                                "core_fraction": core,
                            }
                        )
    for parameter, values in matrix["parameter_neighbors"].items():
        for value in values:
            experiments.append(
                {
                    "id": f"neighbor_{parameter}_{value}",
                    "name": "valuation"
                    if parameter in {"buy_threshold", "sell_threshold"}
                    else "stabilized",
                    "metric": "pe",
                    "window": 10,
                    "core_fraction": 0,
                    "parameter_override": {parameter: value},
                }
            )
    for parameter, values in matrix["sensitivity"].items():
        for value in values:
            experiments.append(
                {
                    "id": f"sensitivity_{parameter}_{value}",
                    "name": "dca",
                    "core_fraction": 0,
                    "sensitivity": {parameter: value},
                }
            )
    return experiments


def windows(dates: pd.DatetimeIndex, config: dict) -> list[dict]:
    """Full sample, chronological splits, overlapping annual windows and walk-forward."""
    first, last = dates[0], dates[-1]
    output = [
        {"id": "full", "start": str(first.date()), "end": str(last.date()), "phase": "descriptive"}
    ]
    split = config["validation"]["split"]
    if len(split) != 3 or not np.isclose(sum(split), 1) or min(split) <= 0:
        raise ValueError("invalid chronological split")
    a, b = int(len(dates) * split[0]), int(len(dates) * sum(split[:2]))
    for label, lo, hi in (("train", 0, a), ("validation", a, b), ("final_holdout", b, len(dates))):
        if hi - lo >= 60:
            output.append(
                {
                    "id": label,
                    "start": str(dates[lo].date()),
                    "end": str(dates[hi - 1].date()),
                    "phase": label,
                }
            )
    for years in config["validation"]["rolling_years"]:
        end = last
        while end - pd.DateOffset(years=years) >= first:
            start = end - pd.DateOffset(years=years)
            output.append(
                {
                    "id": f"rolling_{years}y_{end.date()}",
                    "start": str(start.date()),
                    "end": str(end.date()),
                    "phase": "overlapping_descriptive",
                }
            )
            end -= pd.DateOffset(years=config["validation"]["rolling_step_years"])
    warmup = (
        config["validation"]["walk_forward_train_years"]
        + config["validation"]["walk_forward_validation_years"]
    )
    start = first + pd.DateOffset(years=warmup)
    test_years = config["validation"]["walk_forward_test_years"]
    if test_years < 1:
        raise ValueError("positive walk-forward test length required")
    while start + pd.DateOffset(years=test_years) <= last:
        end = start + pd.DateOffset(years=test_years) - pd.Timedelta(days=1)
        output.append(
            {
                "id": f"walk_forward_{start.date()}",
                "start": str(start.date()),
                "end": str(end.date()),
                "phase": "frozen_rule_test",
                "prior_training_years": config["validation"]["walk_forward_train_years"],
                "prior_validation_years": config["validation"]["walk_forward_validation_years"],
            }
        )
        start += pd.DateOffset(years=test_years)
    return output


def load_tdx(settings: Settings, symbol: str, *, snapshot_id: str | None = None) -> pd.DataFrame:
    """Read only one instrument from pinned Parquet partitions."""
    staging = (
        (SnapshotStore(settings.data_root).path(snapshot_id) / "staging")
        if snapshot_id
        else settings.staging_dir
    )
    with duckdb.connect() as connection:
        frame = connection.execute(
            "SELECT * FROM read_parquet(?) WHERE symbol=? ORDER BY date",
            [str(staging / "daily/**/*.parquet"), symbol],
        ).df()
    if frame.empty:
        raise ValueError(f"no local history for {symbol}")
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")


def save_result(result: Backtest, target: Path) -> None:
    """Persist daily reports and exact decimal journal amounts, without float cash."""
    target.mkdir(parents=True, exist_ok=True)
    result.daily.to_parquet(target / "daily.parquet", compression="zstd")
    journal = result.journal.copy()
    fields = []
    for name in journal:
        sample = journal[name].dropna()
        if len(sample) and isinstance(sample.iloc[0], Decimal):
            journal[name] = journal[name].map(
                lambda value: value if isinstance(value, Decimal) else None
            )
            # Execution prices can carry >6 decimal places; preserve 18 decimals.
            quantum = Decimal("1e-18")
            journal[name] = journal[name].map(
                lambda value: value.quantize(quantum) if value is not None else None
            )
            fields.append(pa.field(name, pa.decimal128(38, 18)))
        else:
            fields.append(pa.field(name, pa.Schema.from_pandas(journal[[name]]).field(name).type))
    pq.write_table(
        pa.Table.from_pandas(journal, schema=pa.schema(fields), preserve_index=False),
        target / "journal.parquet",
        compression="zstd",
    )
    write_json(target / "metrics.json", result.metrics)
    write_json(target / "strategy.json", result.config)


def _load_asset(
    settings: Settings,
    asset: dict,
    catalog: DataCatalog,
    versions: dict,
    *,
    snapshot_id: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    proxy = asset.get("style") == "dividend_lowvol" or asset.get("instrument_kind") == "ETF"
    if asset.get("dataset"):
        dataset = asset["dataset"]
        if dataset not in versions:
            raise ValueError(f"missing dataset {dataset}; access or retention not accepted")
        manifest = catalog.manifest(dataset, versions[dataset])
        frame = catalog.read(dataset, version=versions[dataset])
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.set_index("date")
        return frame, {
            "dataset": dataset,
            "version": manifest["version"],
            "history_type": "ETF_actual_price_history" if proxy else "price_index_reference",
            "basis": "raw_ETF_ex_dividend_price_only" if proxy else "price_only",
            "limitations": [
                "dividends_excluded",
                "publication_vintages_unverified",
                "retention_review_pending",
            ],
            "formal_accepted": False,
        }
    symbol = asset["index"]
    if asset.get("style") == "dividend_lowvol":
        symbol = asset["etfs"][0]
    frame = load_tdx(settings, symbol, snapshot_id=snapshot_id)
    return frame, {
        "dataset": "tdx",
        "symbol": symbol,
        "history_type": "ETF_actual_price_history"
        if proxy
        else "index_may_include_prelaunch_backfill",
        "basis": "raw_ETF_ex_dividend_price_only" if proxy else "price_only",
        "limitations": [
            "corporate_action_pay_dates_unverified",
            "cross_source_units_pending",
            "historical_constituents_and_release_dates_unverified",
        ],
        "formal_accepted": False,
    }


def valuation_features(
    asset: dict,
    bars: pd.DataFrame,
    catalog: DataCatalog,
    versions: dict,
    metric: str,
    window: int | str,
) -> pd.Series:
    """Align published valuation/rates to local closing decisions before ranking."""
    dataset = asset.get("valuation", f"valuation_{asset['id']}")
    if dataset not in versions:
        raise ValueError("missing valuation dataset")
    observed = catalog.observations(dataset, version=versions[dataset])
    observed = observed.rename(
        columns={"pe_index_shares": "pe", "dividend_yield_index_shares": "dividend_yield"}
    )
    timezone, hour = ("America/New_York", 16) if asset["market"] == "US" else ("Asia/Shanghai", 15)
    decisions = (bars.index + pd.Timedelta(hours=hour)).tz_localize(timezone)
    required = (
        {"pe"}
        if metric.startswith("earnings_yield")
        else {"dividend_yield"}
        if metric.startswith("dividend_yield")
        else {metric}
    )
    aligned = pd.DataFrame(index=bars.index)
    for column in required:
        if column not in observed:
            raise ValueError(f"valuation column missing: {column}")
        aligned[column] = align_available(observed, decisions, column).to_numpy()
    if metric.endswith("spread"):
        rate_dataset = "fred_dgs10" if asset["market"] == "US" else "cn_government_10y"
        if rate_dataset not in versions:
            raise ValueError("local government yield with publication times is missing")
        rates = catalog.read(rate_dataset, version=versions[rate_dataset])
        if "bond_yield" not in rates:
            if rate_dataset != "fred_dgs10":
                raise ValueError("explicit decimal bond_yield is required")
            rates["bond_yield"] = rates["close"] / 100
        aligned["bond_yield"] = align_available(rates, decisions, "bond_yield").to_numpy()
    return valuation_temperature(
        aligned,
        metric,
        years=10 if window == "expanding_10" else int(window),
        expanding=window == "expanding_10",
    )


def research_assets(config: dict) -> list[dict]:
    """Separate fixed-candidate ETF/QDII price diagnostics from index research."""
    assets = [dict(asset) for asset in config["universe"]]
    if config.get("include_instrument_price_diagnostics"):
        for asset in config["universe"]:
            if asset.get("style") == "dividend_lowvol":
                continue
            for symbol in asset.get("etfs", []) + asset.get("qdii_candidates", []):
                is_cn = symbol.startswith(("sh", "sz"))
                candidate = {
                    "id": f"{asset['id']}_etf_{symbol.lower()}",
                    "name": f"{asset['name']} {symbol}",
                    "market": "CN" if is_cn else "US",
                    "index": symbol,
                    "underlying": asset["id"],
                    "instrument_kind": "ETF",
                    "etfs": [symbol],
                    "selection": "fixed_candidate_price_diagnostic_not_historical_selection",
                }
                if "valuation" in asset:
                    candidate["valuation"] = asset["valuation"]
                if not is_cn:
                    candidate["dataset"] = f"tiingo_{symbol.lower()}"
                assets.append(candidate)
    return assets


def run_research(
    settings: Settings,
    config_path: Path,
    *,
    exploratory: bool = False,
    replay_run: Path | None = None,
) -> dict:
    """Execute available experiments; publish missing-data rows instead of fake returns."""
    config = load_config(config_path)
    catalog = DataCatalog(settings.data_root)
    store = SnapshotStore(settings.data_root)
    snapshot_id = store.current()
    if not snapshot_id:
        raise ValueError("a published data snapshot is required")
    if not store.verify(snapshot_id)["ok"]:
        raise ValueError("snapshot integrity verification failed")
    current_code = code_revision()
    dependency_lock = Path(__file__).resolve().parents[3] / "requirements-lock.txt"
    lock_hash = sha256_file(dependency_lock)
    pinned_versions = {m["dataset"]: m["version"] for m in catalog.list_datasets()}
    if replay_run:
        original = json.loads((replay_run / "registration.json").read_text())
        if original["config"] != config:
            raise ValueError("replay config differs from frozen registration")
        if original["code"]["sources"] != current_code["sources"]:
            raise ValueError("replay requires identical source bytes")
        if original["snapshot_id"] != snapshot_id:
            raise ValueError("activate the original snapshot before replay")
        if original.get("dependency_lock_sha256") != lock_hash:
            raise ValueError("replay dependency lock differs from registration")
        if original["exploratory"] != exploratory:
            raise ValueError("replay evidence mode differs from registration")
        pinned_versions = original["catalog_versions"]
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = settings.data_root / "research" / now
    directory.mkdir(parents=True)
    experiments = experiment_registry(config)
    registration = {
        "registered_at": utc_now(),
        "protocol_version": config["protocol_version"],
        "config": config,
        "config_sha256": sha256_file(config_path),
        "code": current_code,
        "dependency_lock_sha256": lock_hash,
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": sha256_file(store.path(snapshot_id) / "manifest.json"),
        "catalog_versions": pinned_versions,
        "experiments": experiments,
        "exploratory": exploratory,
        "selection": "none",
        "final_oos_retuning": False,
    }
    write_json(directory / "registration.json", registration)
    rows, coverage = [], []
    execution = config["execution"]
    funding = config["funding"]
    panic_config = config["strategy_matrix"]["panic"]
    primary = config["strategy_matrix"]["primary"]
    default_features = {
        key: panic_config[key] for key in ("drawdown", "sigma", "confirmation", "event_window")
    }
    for asset in research_assets(config):
        name = asset["id"]
        try:
            bars, evidence = _load_asset(
                settings, asset, catalog, pinned_versions, snapshot_id=snapshot_id
            )
        except (ValueError, FileNotFoundError) as exc:
            rows.extend(
                {"asset": name, "experiment": e["id"], "status": "blocked", "reason": str(exc)}
                for e in experiments
            )
            coverage.append({"asset": name, "status": "missing", "reason": str(exc)})
            continue
        release_date = config.get("index_release_dates", {}).get(name)
        evidence["index_release_date"] = release_date
        evidence["prelaunch_rows"] = (
            int((bars.index < pd.Timestamp(release_date)).sum()) if release_date else None
        )
        features = price_features(bars, **default_features)
        coverage.append(
            {
                "asset": name,
                "name": asset["name"],
                "first_date": str(bars.index[0].date()),
                "last_date": str(bars.index[-1].date()),
                "sessions": len(bars),
                **evidence,
                "panic_events": int(features.panic_event.sum()),
            }
        )
        features.to_parquet(directory / f"{name}_features.parquet", compression="zstd")
        available_windows = windows(bars.index, config)
        if release_date and bars.index[0] < pd.Timestamp(release_date):
            live_dates = bars.index[bars.index >= pd.Timestamp(release_date)]
            if len(live_dates) >= 60:
                available_windows.append(
                    {
                        "id": "post_release",
                        "start": str(live_dates[0].date()),
                        "end": str(live_dates[-1].date()),
                        "phase": "published_index_history",
                    }
                )
            backfill_dates = bars.index[bars.index < pd.Timestamp(release_date)]
            if len(backfill_dates) >= 60:
                available_windows.append(
                    {
                        "id": "pre_release_backfill",
                        "start": str(backfill_dates[0].date()),
                        "end": str(backfill_dates[-1].date()),
                        "phase": "backfilled_index_only",
                    }
                )
        write_json(directory / f"{name}_windows.json", available_windows)
        valuation_cache = {}
        for experiment in experiments:
            active_features = features.copy()
            blocker = None
            if not exploratory:
                blocker = "formal_data_gate_not_accepted: PIT/retention/corporate_actions/execution"
            elif experiment.get("metric"):
                key = (experiment["metric"], experiment["window"])
                if key not in valuation_cache:
                    try:
                        valuation_cache[key] = valuation_features(
                            asset, bars, catalog, pinned_versions, *key
                        )
                    except (ValueError, FileNotFoundError):
                        valuation_cache[key] = pd.Series(np.nan, index=bars.index)
                active_features["temperature"] = valuation_cache[key]
                if active_features["temperature"].isna().all():
                    blocker = "insufficient_verified_historical_valuation_and_full_warmup"
            elif experiment["name"] == "kdj" and features.j.isna().all():
                blocker = "close_only_source_has_no_high_low_for_KDJ"
            elif experiment.get("sensitivity", {}).get("dividend_tax_rate") is not None:
                blocker = "cash_dividend_payment_history_missing_tax_sensitivity_not_estimable"
            if blocker:
                rows.append(
                    {
                        "asset": name,
                        "experiment": experiment["id"],
                        "status": "blocked",
                        "reason": blocker,
                    }
                )
                continue
            parameters = {
                **funding,
                "name": experiment["name"],
                "core_fraction": experiment.get("core_fraction", 0),
                "cash_yield": execution["cash_yield"],
                "buy_threshold": primary["buy_threshold"],
                "sell_threshold": primary["sell_threshold"],
                "event_tranches": panic_config["extra_tranches"],
                "cooldown": panic_config["event_window"],
            }
            sensitivity = experiment.get("sensitivity", {})
            for key in ("initial", "cash_yield"):
                if key in sensitivity:
                    parameters[key] = sensitivity[key]
            if "monthly_ratio" in sensitivity:
                parameters["monthly"] = parameters["initial"] * sensitivity["monthly_ratio"]
            if experiment.get("exit_style"):
                parameters["exit_style"] = experiment["exit_style"]
            overrides = experiment.get("parameter_override", {})
            mapping = {
                "extra_tranches": "event_tranches",
                "buy_threshold": "buy_threshold",
                "sell_threshold": "sell_threshold",
            }
            for key, target_key in mapping.items():
                if key in overrides:
                    parameters[target_key] = overrides[key]
            feature_parameters = {
                key: overrides[key] for key in ("confirmation",) if key in overrides
            }
            for key, target_key in (("panic_drawdown", "drawdown"), ("panic_sigma", "sigma")):
                if key in overrides:
                    feature_parameters[target_key] = overrides[key]
            if feature_parameters:
                revised = price_features(bars, **(default_features | feature_parameters))
                if "temperature" in active_features:
                    revised["temperature"] = active_features["temperature"]
                active_features = revised
            strategy = Strategy(**parameters)
            costs = Costs(
                dec(sensitivity.get("commission_rate", execution["commission_rate"])),
                dec(execution["minimum_commission"]),
                dec(execution["slippage_bps"]),
                dec(0),
            )
            # Sensitivity uses full history; primary variants use every frozen window.
            selected_windows = available_windows[:1] if sensitivity else available_windows
            for window in selected_windows:
                if experiment.get("metric"):
                    first_trade = bars.index.searchsorted(pd.Timestamp(window["start"]))
                    if first_trade == 0 or pd.isna(
                        active_features["temperature"].iloc[first_trade - 1]
                    ):
                        rows.append(
                            {
                                "asset": name,
                                "experiment": experiment["id"],
                                "window": window["id"],
                                "status": "blocked",
                                "reason": "window_start_has_no_valuation_warmup_use_common_eligible_window",
                            }
                        )
                        continue
                try:
                    result = run_strategy(
                        bars,
                        active_features,
                        strategy,
                        symbol=name,
                        start=window["start"],
                        end=window["end"],
                        costs=costs,
                        lot=dec(
                            execution["cn_etf_lot" if asset["market"] == "CN" else "us_etf_lot"]
                            if "ETF" in evidence["basis"]
                            else execution["index_proxy_lot"]
                        ),
                        price_basis=evidence["basis"],
                        execution="next_open" if "open" in bars else "next_close",
                    )
                    target = directory / name / experiment["id"] / window["id"]
                    save_result(result, target)
                    rows.append(
                        {
                            "asset": name,
                            "experiment": experiment["id"],
                            "window": window["id"],
                            "phase": window["phase"],
                            "status": "exploratory_price_only",
                            "index_release_date": release_date,
                            "contains_prelaunch": bool(
                                release_date
                                and pd.Timestamp(window["start"]) < pd.Timestamp(release_date)
                            ),
                            **result.metrics,
                        }
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "asset": name,
                            "experiment": experiment["id"],
                            "window": window["id"],
                            "status": "failed",
                            "reason": f"{type(exc).__name__}: {exc}",
                        }
                    )
        logger.info("%s research complete (%s)", name, evidence["basis"])
    for pair in config["style_pairs"]:
        try:
            if not exploratory:
                raise ValueError("formal total-return and ETF-selection data gates not passed")
            if any(not s.startswith(("sh", "sz")) for s in pair["symbols"]):
                raise ValueError("US ETF dividend/price archive unavailable")
            prices = {
                symbol: load_tdx(settings, symbol, snapshot_id=snapshot_id)
                for symbol in pair["symbols"]
            }
            result = run_allocation(
                prices,
                **funding,
                weights=dict(zip(pair["symbols"], pair["weights"], strict=True)),
                costs=Costs(
                    dec(execution["commission_rate"]),
                    dec(execution["minimum_commission"]),
                    dec(execution["slippage_bps"]),
                    dec(execution["dividend_tax_rate"]),
                ),
                lot=dec(execution["cn_etf_lot"]),
            )
            save_result(result, directory / pair["id"] / "style_annual_rebalance")
            rows.append(
                {
                    "asset": pair["id"],
                    "experiment": "style_annual_rebalance",
                    "window": "common_history",
                    "status": "exploratory_price_only",
                    "reason": "cash_dividends_missing_not_valid_for_style_ranking",
                    **result.metrics,
                }
            )
        except (ValueError, FileNotFoundError) as exc:
            rows.append(
                {
                    "asset": pair["id"],
                    "experiment": "style_annual_rebalance",
                    "status": "blocked",
                    "reason": str(exc),
                }
            )
    for extension in config["extensions"]:
        rows.append(
            {
                "asset": "all",
                "experiment": extension["id"],
                "status": "blocked",
                "reason": extension["gate"],
            }
        )
    table = pd.DataFrame(rows)
    # Opportunity cost is defined only for identical funding and dates.
    table["wealth_gap_vs_dca"] = np.nan
    if "window" in table:
        for (asset, window), indices in table.groupby(["asset", "window"]).groups.items():
            group = table.loc[indices]
            base = group[group.experiment == "dca"]
            if len(base) == 1:
                same_funding = group.contributed == base.iloc[0].contributed
                selected_indices = group.index[same_funding]
                table.loc[selected_indices, "wealth_gap_vs_dca"] = (
                    table.loc[selected_indices, "ending_wealth"] - base.iloc[0].ending_wealth
                )
    table.to_parquet(directory / "results.parquet", index=False, compression="zstd")
    table.to_csv(directory / "results.csv", index=False)
    write_json(directory / "coverage.json", coverage)
    summary = {
        "run_id": now,
        "directory": str(directory),
        "snapshot_id": snapshot_id,
        "registered_experiments": len(experiments),
        "result_rows": len(rows),
        "status_counts": table.status.value_counts().to_dict(),
        "formal_conclusions": False,
        "results_sha256": sha256_file(directory / "results.parquet"),
    }
    write_json(directory / "summary.json", summary)
    make_report(directory, table, coverage, summary)
    if replay_run:
        previous = pd.read_parquet(replay_run / "results.parquet")
        pd.testing.assert_frame_equal(table, previous)
        write_json(
            directory / "replay.json", {"original": str(replay_run), "identical_results": True}
        )
    write_json(settings.data_root / "research/latest.json", summary)
    return summary


def make_report(directory: Path, table: pd.DataFrame, coverage: list[dict], summary: dict) -> None:
    """Make evidence limits visible before any return number."""
    lines = [
        "# 宽基与红利低波研究执行报告",
        "",
        "本轮是价格口径的探索与工程验证，不是已验收的可投资总回报，也不产生买卖推荐。",
        "PE/PB/股息率择时缺少经验证的长期估值和发布时间历史，已逐项暂停；不得用价格分位冒充PE分位。",
        "ETF现金分红尚未补齐，因此红利低波的价格结果不能用于评价该风格优劣。",
        "指数研究可能含发布前回溯；FRED标普500仅约10年且不含分红。指数价格不可直接成交。",
        "",
        f"快照：`{summary['snapshot_id']}`；冻结清单见 `registration.json`；全结果见 `results.csv`。",
        "",
        "## 数据覆盖",
        "",
        pd.DataFrame(coverage)
        .drop(columns=["limitations"], errors="ignore")
        .to_markdown(index=False),
        "",
        "## 可执行的价格基准（本金10万，每月1000，现金0收益）",
        "",
    ]
    if {"window", "annualized_return", "ending_wealth"}.issubset(table):
        chosen = table[
            (table.window == "full")
            & table.experiment.isin(["lump_sum", "dca", "kdj", "kdj_core50"])
            & (table.status == "exploratory_price_only")
        ]
        columns = [
            "asset",
            "experiment",
            "start",
            "end",
            "annualized_return",
            "xirr",
            "max_drawdown",
            "ending_wealth",
            "average_cash_fraction",
        ]
        lines.append(chosen[columns].to_markdown(index=False, floatfmt=".4f"))
        valid = table[
            (table.status == "exploratory_price_only")
            & table.window.str.startswith("rolling_", na=False)
        ]
        if len(valid):
            lines += [
                "",
                "## 重叠滚动窗口（并非独立样本）",
                "",
                valid.groupby(["asset", "experiment"])
                .agg(
                    windows=("annualized_return", "count"),
                    worst_annualized=("annualized_return", "min"),
                    median_annualized=("annualized_return", "median"),
                    worst_drawdown=("max_drawdown", "min"),
                )
                .to_markdown(floatfmt=".4f"),
            ]
    gaps = (
        table[table.status.isin(["blocked", "failed"])]
        .groupby(["status", "reason"], dropna=False)
        .size()
        .rename("count")
    )
    lines += [
        "",
        "## 未通过的研究门槛",
        "",
        gaps.to_markdown(),
        "",
        "尚未依据最终样本外选择策略。30%回撤是研究目标，不是保证。",
        "后续补齐数据后应新建注册版本、独立保留本轮所有成功/失败/暂停实验。",
    ]
    (directory / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
