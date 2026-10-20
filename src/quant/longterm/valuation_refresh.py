"""Re-evaluate all prespecified Shiller proxies on an explicitly new source vintage."""

import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from quant.config import Settings
from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, utc_now, write_json
from quant.etl.restart import code_revision
from quant.longterm.pool_research import _run_asset, make_pool_report


def run_shiller_refresh(
    settings: Settings,
    source: Path,
    output: Path,
    *,
    version: str | None = None,
    replay_run: Path | None = None,
) -> dict:
    """Change only the monthly vintage; reuse all registered valuation rules."""
    if output.exists():
        raise ValueError("preserve previous valuation experiments")
    prior = json.loads((source / "registration.json").read_text())
    catalog = DataCatalog(settings.data_root)
    manifest = catalog.manifest("shiller_monthly", version)
    registration = prior | {
        "registered_at": utc_now(),
        "parent_primary_run": str(source.resolve()),
        "parent_registration_sha256": sha256_file(source / "registration.json"),
        "code": code_revision(),
        "catalog_versions": prior["catalog_versions"] | {"shiller_monthly": manifest["version"]},
        "experiments": [
            e for e in prior["experiments"] if e.get("valuation_source") == "shiller_proxy"
        ],
        "universe": [asset for asset in prior["universe"] if asset["id"] == "sp500"],
        "primary_price_sha256": sha256_file(source / "inputs" / "sp500.parquet"),
        "selection": "all_previously_registered_Shiller_rules_no_threshold_search",
        "formal_accepted": False,
    }
    if replay_run:
        original = json.loads((replay_run / "registration.json").read_text())
        for key in ("parent_registration_sha256", "primary_price_sha256", "experiments"):
            if original[key] != registration[key]:
                raise ValueError(f"valuation replay mismatch: {key}")
        if original["code"]["sources"] != registration["code"]["sources"]:
            raise ValueError("valuation replay requires identical source bytes")
        registration = original
    new_version = registration["catalog_versions"]["shiller_monthly"]
    old_version = prior["catalog_versions"]["shiller_monthly"]
    if new_version == old_version:
        raise ValueError("this audit requires a distinct monthly source vintage")
    output.mkdir(parents=True)
    (output / "inputs").mkdir()
    shutil.copyfile(source / "inputs" / "sp500.parquet", output / "inputs" / "sp500.parquet")
    write_json(output / "registration.json", registration)
    frames = [
        catalog.read("shiller_monthly", version=identifier).set_index("date")
        for identifier in (old_version, new_version)
    ]
    joined = frames[0].join(frames[1], how="outer", lsuffix="_old", rsuffix="_new")
    changes = {}
    for column in frames[0].select_dtypes(include="number"):
        old, new = joined[f"{column}_old"], joined[f"{column}_new"]
        valid = old.notna() & new.notna()
        changes[column] = {
            "overlapping_observations": int(valid.sum()),
            "revised_overlapping_values": int(
                (valid & ~np.isclose(old, new, rtol=1e-10, atol=1e-10, equal_nan=True)).sum()
            ),
            "newly_available_values": int((old.isna() & new.notna()).sum()),
            "removed_values": int((old.notna() & new.isna()).sum()),
        }
    joined.to_parquet(output / "vintage_comparison.parquet", compression="zstd")
    write_json(
        output / "vintage_summary.json",
        {"old_version": old_version, "new_version": new_version, "fields": changes},
    )
    evidence = next(
        row for row in json.loads((source / "coverage.json").read_text()) if row["asset"] == "sp500"
    )
    coverage = [
        evidence
        | {
            "valuation_dataset_version": new_version,
            "valuation_status": "revised_interpolated_monthly_proxy_not_historical_PIT",
        }
    ]
    write_json(output / "coverage.json", coverage)
    outcome = _run_asset(
        {
            "directory": str(output),
            "data_root": str(settings.data_root),
            "asset": registration["universe"][0],
            "evidence": evidence,
            "actions": None,
            "research_start": evidence["funding_start_after_shared_warmup"],
        }
    )
    table = pd.read_parquet(output / "sp500" / "results.parquet")
    table.to_parquet(output / "results.parquet", compression="zstd")
    table.to_csv(output / "results.csv", index=False)
    summary = {
        "directory": str(output),
        "experiments": len(registration["experiments"]),
        "records": len(table),
        "statuses": table.status.value_counts().to_dict(),
        "outcomes": [outcome],
        "formal_accepted": False,
        "selection": "none",
    }
    make_pool_report(output, table, coverage, summary)
    computed = table[table.status.eq("computed")]
    columns = [
        "experiment",
        "window",
        "start",
        "end",
        "annualized_return",
        "xirr",
        "max_drawdown",
        "average_cash_fraction",
        "initial_wait_days",
        "initial_wait_censored",
        "trades",
        "delta_ending_wealth_vs_pool",
    ]
    shown = computed[computed.window.isin(["full", "latest_5y"])]
    shown[columns].to_csv(output / "valuation_full_and_5y.csv", index=False)
    (output / "valuation_report.md").write_text(
        "# 全部已登记估值代理：维护中来源的新版本\n\n"
        "保持原PE/CAPE/股息率、利差、滞后、退出和阶段规则；没有收益选优。\n"
        "工作簿为修订后的月度平均及插值盈利，不是当年已知数据；不能用作正式估值择时业绩。\n"
        "价格成交仍使用原冻结日线；不把月均指数价格当成可交易价格。\n"
        "每行相对基准的财富差使用相同起止日、入金和成本；原2023年截止来源的运行单独保留。\n\n"
        + shown[columns].to_markdown(index=False)
        + "\n\n所有滚动窗口、失败及暂停见results.csv；来源修订逐字段见vintage_summary.json。\n"
    )
    write_json(output / "summary.json", summary)
    payloads = {
        str(path.relative_to(output)): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name not in {"registration.json", "progress.json", "summary.json"}
        and path.suffix != ".txt"
    }
    write_json(output / "payloads.json", payloads)
    if replay_run:
        previous = json.loads((replay_run / "payloads.json").read_text())
        changed = sorted(
            name
            for name in set(previous) | set(payloads)
            if previous.get(name) != payloads.get(name)
        )
        replay = {"identical": not changed, "changed_files": changed, "payloads": len(payloads)}
        write_json(output / "replay.json", replay)
        summary["replay"] = replay
    return summary


def run_current_pe_study(
    settings: Settings,
    source: Path,
    output: Path,
    config_path: Path,
    *,
    replay_run: Path | None = None,
) -> dict:
    """Add an explicitly separate current-price formulation using the same cash engine."""
    from quant.config import load_config
    from quant.longterm.current_pe import current_pe_registry
    from quant.longterm.stages import qualify_value_events

    if output.exists():
        raise ValueError("preserve previous valuation studies")
    config = load_config(config_path)
    prior = json.loads((source / "registration.json").read_text())
    catalog = DataCatalog(settings.data_root)
    version = catalog.manifest("shiller_monthly")["version"]
    registration = prior | {
        "registered_at": utc_now(),
        "parent_primary_run": str(source),
        "parent_registration_sha256": sha256_file(source / "registration.json"),
        "code": code_revision(),
        "current_pe_config": config,
        "catalog_versions": prior["catalog_versions"] | {"shiller_monthly": version},
        "experiments": current_pe_registry(config, prior["config"]),
        "universe": [asset for asset in prior["universe"] if asset["id"] == "sp500"],
        "primary_price_sha256": sha256_file(source / "inputs/sp500.parquet"),
        "study_origin": "formulation_audit_after_observing_lagged_whole_PE_results",
        "selection": "all_registered_supplementary_proxies",
        "formal_accepted": False,
    }
    if replay_run:
        original = json.loads((replay_run / "registration.json").read_text())
        for key in (
            "parent_registration_sha256",
            "primary_price_sha256",
            "experiments",
            "current_pe_config",
        ):
            if original[key] != registration[key]:
                raise ValueError(f"current PE replay mismatch: {key}")
        if original["code"]["sources"] != registration["code"]["sources"]:
            raise ValueError("current PE replay requires identical source bytes")
        registration = original
    output.mkdir(parents=True)
    (output / "inputs").mkdir()
    shutil.copyfile(source / "inputs/sp500.parquet", output / "inputs/sp500.parquet")
    write_json(output / "registration.json", registration)
    evidence = next(
        row for row in json.loads((source / "coverage.json").read_text()) if row["asset"] == "sp500"
    )
    coverage = [
        evidence
        | {"valuation_status": "current_price_revised_lagged_earnings_monthly_reference_proxy"}
    ]
    write_json(output / "coverage.json", coverage)
    outcome = _run_asset(
        {
            "directory": str(output),
            "data_root": str(settings.data_root),
            "asset": registration["universe"][0],
            "evidence": evidence,
            "actions": None,
            "research_start": evidence["funding_start_after_shared_warmup"],
        }
    )
    table = pd.read_parquet(output / "sp500/results.parquet")
    table.to_parquet(output / "results.parquet", compression="zstd")
    table.to_csv(output / "results.csv", index=False)
    summary = {
        "experiments": len(registration["experiments"]),
        "records": len(table),
        "statuses": table.status.value_counts().to_dict(),
        "outcomes": [outcome],
        "formal_accepted": False,
        "selection": "none",
    }
    make_pool_report(output, table, coverage, summary)
    stages = pd.read_parquet(output / "sp500/stages.parquet")
    stages = stages.loc[evidence["funding_start_after_shared_warmup"] :]
    counts = []
    for path in sorted((output / "sp500/valuation_inputs").glob("daily_*.parquet")):
        values = pd.read_parquet(path).temperature.reindex(stages.index)
        features = qualify_value_events(stages.assign(temperature=values), config["buy_threshold"])
        for label, part in (
            ("full", features),
            ("latest_5y", features.loc[features.index[-1] - pd.DateOffset(years=5) :]),
        ):
            cheap = part.temperature.lt(config["buy_threshold"])
            counts.append(
                {
                    "temperature": path.stem,
                    "window": label,
                    "known_sessions": int(part.temperature.notna().sum()),
                    "cheap_sessions": int(cheap.sum()),
                    "pressure_events": int(part.pressure.sum()),
                    "cheap_pressure_events": int((cheap & part.pressure).sum()),
                    "qualified_stabilized_events": int(
                        (cheap & part.event_value_eligible & part.stabilized).sum()
                    ),
                }
            )
    pd.DataFrame(counts).to_csv(output / "stage_counts.csv", index=False)
    shown = table[table.status.eq("computed") & table.window.isin(["full", "latest_5y"])]
    columns = [
        "experiment",
        "window",
        "annualized_return",
        "max_drawdown",
        "average_cash_fraction",
        "initial_wait_days",
        "trades",
        "delta_ending_wealth_vs_pool",
    ]
    shown[columns].to_csv(output / "full_and_5y.csv", index=False)
    (output / "proxy_formulation.md").write_text(
        "# 现价与滞后盈利：全部补充对照\n\n"
        "此组在检查整条滞后PE后追加，不是未看过结果的最终样本外。\n"
        "当前分子为每日指数收盘；历史参考为过去月均价格除以同期假定已知盈利。\n"
        "分母仍是Shiller修订/插值数据，6/12月是可得时间假设，月频参考与日频现价存在频率差异。\n"
        "这不是官方历史PE或PIT投资业绩。同日历、同资金、同底仓的现金池作为对照。\n\n"
        + shown[columns].to_markdown(index=False)
        + "\n\n阶段计数见stage_counts.csv；所有窗口及负面结果见results.csv；未挑选冠军。\n"
    )
    write_json(output / "summary.json", summary)
    payloads = {
        str(path.relative_to(output)): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name not in {"registration.json", "progress.json", "summary.json"}
    }
    write_json(output / "payloads.json", payloads)
    if replay_run:
        previous = json.loads((replay_run / "payloads.json").read_text())
        changed = sorted(
            name
            for name in set(previous) | set(payloads)
            if previous.get(name) != payloads.get(name)
        )
        write_json(
            output / "replay.json",
            {"identical": not changed, "changed_files": changed, "payloads": len(payloads)},
        )
    return summary
