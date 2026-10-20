"""Reproducible style portfolios and clearly labelled currency/premium scenarios."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import traceback

import numpy as np
import pandas as pd

from quant.config import Settings, load_config
from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, utc_now, write_json
from quant.etl.restart import code_revision
from quant.longterm.action_audit import verify_action_ledger
from quant.longterm.asset_inputs import prepare_action_prices
from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.diagnostics import drawdown_episode, verify_price_ledger
from quant.longterm.features import align_available
from quant.longterm.ledger import Costs, dec
from quant.longterm.pool_registry import pool_windows
from quant.longterm.research import save_result
from quant.longterm.stages import StageSpec, stage_features
from quant.longterm.style_pool import run_style_pool, verify_style_ledger


def load_study_asset(
    source: Path, name: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    """Use only inputs pinned by the primary registration."""
    bars = pd.read_parquet(source / "inputs" / f"{name}.parquet")
    path = source / "inputs" / f"{name}_actions.parquet"
    if not path.exists():
        return bars, bars.copy(), None
    actions = pd.read_parquet(path)
    execution, signals, _ = prepare_action_prices(bars, actions)
    return execution, signals, actions


def save_extension_case(result, audit: dict, path: Path, record: dict, root: Path) -> dict:
    """Preserve journals and adverse outcomes with the same accounting definitions."""
    save_result(result, path)
    write_json(path / "ledger_audit.json", audit)
    episode = drawdown_episode(result.daily.twr_nav)
    record.update(
        status="computed",
        **result.metrics,
        independent_ledger_verified=audit["ok"],
        drawdown_peak=episode["peak_date"],
        drawdown_trough=episode["trough_date"],
        drawdown_recovery=episode["recovery_date"],
        worst_drawdown_recovery_days=episode["peak_to_recovery_days"],
        drawdown_unrecovered=episode["unrecovered"],
        price_profit_net_costs=result.metrics["ending_profit"]
        - result.metrics["gross_dividends"]
        + result.metrics["dividend_tax"],
        result_directory=str(path.relative_to(root)),
    )
    write_json(path / "record.json", record)
    return record


def _failed_case(path: Path, record: dict, exc: Exception) -> dict:
    path.mkdir(parents=True, exist_ok=True)
    record.update(status="error", reason=repr(exc))
    (path / "error.txt").write_text(traceback.format_exc())
    write_json(path / "record.json", record)
    return record


def run_style_cases(
    source: Path, root: Path, config: dict, primary: dict, costs: Costs
) -> list[dict]:
    settings = config["style_portfolios"]
    if settings["weight"] != 0.5:
        raise ValueError("this registered style experiment uses two equal weights")
    records = []
    coverage = {row["asset"]: row for row in json.loads((source / "coverage.json").read_text())}
    for pair in settings["pairs"]:
        name = "__".join(pair)
        inputs = {asset: load_study_asset(source, asset) for asset in pair}
        bars = {asset: item[0] for asset, item in inputs.items()}
        actions = {asset: item[2] for asset, item in inputs.items()}
        if any(value is None for value in actions.values()):
            records.append(
                {
                    "group": "style",
                    "asset": name,
                    "status": "blocked",
                    "reason": "company_actions_missing",
                }
            )
            continue
        calendar = bars[pair[0]].index.intersection(bars[pair[1]].index)
        first = max(pd.Timestamp(coverage[a]["funding_start_after_shared_warmup"]) for a in pair)
        windows = pool_windows(calendar[calendar >= first], primary)
        features = {a: stage_features(inputs[a][1], StageSpec(**primary["stages"])) for a in pair}
        for window in windows:
            funding = {k: settings[k] for k in ("initial", "monthly", "tranches")}
            for reinvest in settings["reinvest_dividends"]:
                for rebalance in settings["annual_rebalance"]:
                    identifier = f"equal_style_annual{int(rebalance)}_reinvest{int(reinvest)}"
                    path = root / "style" / name / identifier / window["id"]
                    record = {
                        "group": "style",
                        "asset": name,
                        "experiment": identifier,
                        "window": window["id"],
                        "basis": "named_ETF_actual_prices_actions_CNY",
                        "formal_accepted": False,
                    }
                    try:
                        result = run_style_pool(
                            bars,
                            actions,
                            start=window["start"],
                            end=window["end"],
                            **funding,
                            annual_rebalance=rebalance,
                            reinvest_dividends=reinvest,
                            costs=costs,
                        )
                        closes = pd.DataFrame({a: b.close for a, b in bars.items()})
                        audit = verify_style_ledger(result, closes, actions, costs)
                        records.append(save_extension_case(result, audit, path, record, root))
                    except Exception as exc:
                        records.append(_failed_case(path, record, exc))
                for asset in pair:
                    identifier = f"single_{asset}_reinvest{int(reinvest)}"
                    path = root / "style" / name / identifier / window["id"]
                    record = {
                        "group": "style",
                        "asset": name,
                        "experiment": identifier,
                        "window": window["id"],
                        "basis": "named_ETF_actual_prices_actions_CNY",
                        "formal_accepted": False,
                    }
                    try:
                        result = run_cash_pool(
                            bars[asset],
                            features[asset],
                            PoolPolicy(
                                entry="unconditional",
                                exit="none",
                                reinvest_dividends=reinvest,
                                **funding,
                            ),
                            symbol=actions[asset].symbol.iloc[0],
                            start=window["start"],
                            end=window["end"],
                            actions=actions[asset],
                            costs=costs,
                            lot=dec(100),
                        )
                        audit = verify_action_ledger(
                            result, bars[asset].close, actions[asset], costs
                        )
                        records.append(save_extension_case(result, audit, path, record, root))
                    except Exception as exc:
                        records.append(_failed_case(path, record, exc))
        write_json(root / "progress.json", {"completed_style_pair": name, "records": len(records)})
    return records


def run_currency_cases(
    source: Path,
    root: Path,
    config: dict,
    primary: dict,
    catalog: DataCatalog,
    versions: dict,
    costs: Costs,
) -> list[dict]:
    """A price-index conversion/premium sensitivity, never a fabricated QDII track record."""
    settings = config["fx_and_premium"]
    observed = catalog.read(settings["exchange_rate"], version=versions[settings["exchange_rate"]])
    records = []
    for asset in settings["assets"]:
        bars, signals, _ = load_study_asset(source, asset)
        decisions = (bars.index + pd.Timedelta(hours=16)).tz_localize("America/New_York")
        fx = align_available(
            observed,
            decisions,
            "close",
            maximum_age_days=settings["maximum_fx_staleness_days"],
        )
        fx.index = bars.index
        fx = fx.shift(settings["fx_lag_sessions"] - 1)
        # An old known FX quote may mark a holding, but may not authorize a
        # fresh trade. Never backfill missing history from a future quote.
        marks = align_available(observed, decisions, "close", maximum_age_days=365000)
        marks.index = bars.index
        marks = marks.shift(settings["fx_lag_sessions"] - 1)
        eligible = fx.notna() & (
            bars.index
            >= max(
                bars.index[primary["validation"]["initial_price_warmup"]],
                pd.Timestamp(settings["first_currency_scenario"]),
            )
        )
        allowed = bars.index[eligible]
        if not len(allowed):
            records.append(
                {"group": "currency", "asset": asset, "status": "blocked", "reason": "no_usable_fx"}
            )
            continue
        price = bars.close * marks
        features = stage_features(signals, StageSpec(**primary["stages"]))
        base_policy = PoolPolicy(**primary["funding"], exit="none")
        for window in pool_windows(allowed, primary):
            index = bars.loc[window["start"] : window["end"]].index
            if price.loc[index].isna().any():
                records.append(
                    {
                        "group": "currency",
                        "asset": asset,
                        "window": window["id"],
                        "status": "blocked",
                        "reason": "stale_fx_within_window",
                    }
                )
                continue
            for premium in settings["initial_premium"]:
                decay = np.clip(
                    1 - (index - index[0]).days / settings["premium_decay_calendar_days"], 0, 1
                )
                # Fixed scenario path announced in the configuration, not fitted
                # to historical ETF premiums or chosen after observing returns.
                execution = pd.DataFrame({"close": price.loc[index] * (1 + premium * decay)})
                for entry in ("unconditional", "stabilized"):
                    identifier = f"cny_{entry}_premium{premium:g}"
                    path = root / "currency" / asset / identifier / window["id"]
                    record = {
                        "group": "currency",
                        "asset": asset,
                        "experiment": identifier,
                        "window": window["id"],
                        "premium": premium,
                        "basis": "CNY_translated_price_index_hypothetical_premium",
                        "formal_accepted": False,
                        "fx_release_assumption": "provider_daily_timestamp_not_verified_H10_release",
                        "stale_fx_trade_pauses": int(fx.loc[index].isna().sum()),
                    }
                    try:
                        # Preserve the preceding signal before the funding start.
                        all_execution = pd.DataFrame({"close": price, "tradable": fx.notna()})
                        all_execution = all_execution.loc[price.first_valid_index() :]
                        all_execution.loc[index, "close"] = execution.close
                        result = run_cash_pool(
                            all_execution,
                            features.loc[all_execution.index],
                            replace(base_policy, entry=entry),
                            symbol=asset,
                            start=window["start"],
                            end=window["end"],
                            costs=costs,
                        )
                        audit = verify_price_ledger(result, all_execution.close)
                        records.append(save_extension_case(result, audit, path, record, root))
                    except Exception as exc:
                        records.append(_failed_case(path, record, exc))
        write_json(
            root / "progress.json", {"completed_currency_asset": asset, "records": len(records)}
        )
    return records


def run_pool_extensions(
    settings: Settings,
    source: Path,
    config_path: Path,
    *,
    replay_run: Path | None = None,
) -> dict:
    """Freeze this additive experiment before its own scoring; preserve the primary run."""
    config = load_config(config_path)
    reference = json.loads((source / "registration.json").read_text())
    catalog = DataCatalog(settings.data_root)
    versions = dict(reference["catalog_versions"])
    for name in ("cboe_vxn", "cboe_skew", "cboe_total_putcall", "sse_margin_daily"):
        try:
            versions[name] = catalog.manifest(name)["version"]
        except FileNotFoundError:
            pass
    registration = {
        "registered_at": utc_now(),
        "source": str(source.resolve()),
        "config": config,
        "code": code_revision(),
        "catalog_versions": versions,
        "primary_registration_sha256": sha256_file(source / "registration.json"),
        "inputs": {p.name: sha256_file(p) for p in sorted((source / "inputs").glob("*.parquet"))},
        "selection": "none",
        "formal_accepted": False,
    }
    if replay_run:
        prior = json.loads((replay_run / "registration.json").read_text())
        for key in ("config", "primary_registration_sha256", "inputs"):
            if prior[key] != registration[key]:
                raise ValueError(f"extension replay mismatch: {key}")
        if prior["code"]["sources"] != registration["code"]["sources"]:
            raise ValueError("extension replay requires identical source bytes")
        registration, versions = prior, prior["catalog_versions"]
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%fZ")
    root = settings.data_root / "research" / f"cash-pool-extensions-{stamp}"
    root.mkdir(parents=True)
    write_json(root / "registration.json", registration)
    primary = reference["config"]
    defaults = primary["execution"]
    costs = Costs(
        commission_rate=dec(defaults["commission_rate"]),
        minimum_commission=dec(defaults["minimum_commission"]),
        slippage_bps=dec(defaults["slippage_bps"]),
    )
    rows = run_style_cases(source, root, config, primary, costs)
    rows += run_currency_cases(source, root, config, primary, catalog, versions, costs)
    from quant.longterm.pressure_research import run_pressure_cases

    rows += run_pressure_cases(source, root, config, primary, catalog, versions, costs)
    table = pd.DataFrame(rows)
    table.to_parquet(root / "results.parquet", compression="zstd")
    table.to_csv(root / "results.csv", index=False)
    summary = {
        "directory": str(root),
        "records": len(rows),
        "statuses": table.status.value_counts().to_dict(),
        "formal_accepted": False,
    }
    write_json(root / "summary.json", summary)
    payloads = {
        str(p.relative_to(root)): sha256_file(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and p.name not in {"registration.json", "progress.json", "summary.json"}
        and p.suffix != ".txt"
    }
    write_json(root / "payloads.json", payloads)
    if replay_run:
        old = json.loads((replay_run / "payloads.json").read_text())
        changed = sorted(k for k in set(old) | set(payloads) if old.get(k) != payloads.get(k))
        summary["replay"] = {
            "identical": not changed,
            "changed_files": changed,
            "payloads": len(payloads),
        }
        write_json(root / "replay.json", summary["replay"])
    return summary
