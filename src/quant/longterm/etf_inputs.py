"""Freeze verified ETF cash inputs and archive-time feature evidence for research."""

from __future__ import annotations

import json
import base64
import hashlib
from pathlib import Path
import shutil

import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.longterm.etf_sources import (
    calendar_check,
    chart_prices,
    combine_distribution_evidence,
    issuer_table_actions,
    nasdaq_actions,
    ssga_actions,
    validate_actions,
)
from quant.longterm.stages import StageSpec, qualify_value_events, stage_features
from quant.longterm.vintage_valuation import archive_temperature, parse_shiller_vintage


def archive_observations(source_root: Path) -> tuple[pd.DataFrame, list[dict]]:
    """Every success and rejection is retained; a refused request is not a vintage."""
    tables, evidence = [], []
    for receipt in sorted(source_root.glob("shiller_*.json")):
        meta = json.loads(receipt.read_text())
        path = receipt.with_suffix(".raw")
        row = dict(file=path.name, receipt_sha256=sha256_file(receipt))
        if meta.get("status") != 200:
            evidence.append(
                row | {"status": "unavailable", "reason": meta.get("error", meta.get("status"))}
            )
            continue
        if sha256_file(path) != meta["sha256"]:
            raise ValueError("vintage source bytes changed")
        archive_digest = base64.b32encode(hashlib.sha1(path.read_bytes()).digest()).decode()
        if archive_digest != meta["cdx"][5]:
            evidence.append(row | {"status": "rejected", "reason": "CDX response digest mismatch"})
            continue
        stamp = meta["cdx"][1]
        # Archive redirects to a different version cannot inherit an earlier date.
        actual = (
            meta.get("final_url", meta["url"]).split("/web/")[1].split("/")[0].removesuffix("id_")
        )
        if actual != stamp:
            evidence.append(
                row | {"status": "rejected", "reason": "archive redirected to another capture"}
            )
            continue
        available = pd.to_datetime(stamp, format="%Y%m%d%H%M%S", utc=True)
        try:
            frame = parse_shiller_vintage(path, available.isoformat())
        except (ValueError, KeyError) as exc:
            evidence.append(row | {"status": "parse_rejected", "reason": str(exc)})
            continue
        tables.append(frame)
        evidence.append(
            row
            | {
                "status": "parsed",
                "available_at": available.isoformat(),
                "rows": len(frame),
                "raw_sha256": meta["sha256"],
            }
        )
    if not tables:
        raise ValueError("no usable valuation vintages")
    return pd.concat(tables, ignore_index=True), evidence


def _features(signals, rule, config, value):
    features = stage_features(
        signals,
        StageSpec(
            **(config["stage"] | {"event_window": rule["expiry"], "drawdown": rule["drawdown"]})
        ),
    )
    if rule["lag"]:
        features["temperature"] = value.temperature
        if rule["entry"].startswith("value_"):
            features = (
                qualify_value_during_stress(features, rule["buy"])
                if rule.get("event_value_mode") == "during_event_stress"
                else qualify_value_events(features, rule["buy"])
            )
    return features


def qualify_value_during_stress(features: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """An ongoing stress event can become cheap later, with no retroactive flag.

    Entry still independently requires cheap valuation at the confirmation date.
    This registered alternative does not alter the original event-onset rule.
    """
    eligible, flags = set(), []
    for row in features.itertuples():
        if (
            pd.notna(row.event_id)
            and row.stress
            and pd.notna(row.temperature)
            and row.temperature < threshold
        ):
            eligible.add(row.event_id)
        flags.append(pd.notna(row.event_id) and row.event_id in eligible)
    out = features.copy()
    out["event_value_eligible"] = flags
    return out


def prepare_etf_inputs(data_root: Path, root: Path, config: dict) -> dict:
    """Keep ETF prices, underlying-index signals and real dividend cash distinct."""
    base = root / "inputs"
    if config.get("frozen_etf_parent"):
        return reuse_etf_inputs(data_root, root, config)
    base.mkdir()
    sources = data_root / config["source_directory"]
    parent = data_root / "research" / config["input_parent"]
    parent_hashes = json.loads((parent / "payloads.json").read_text())
    source_hashes = {}

    def source(path):
        source_hashes[str(path.relative_to(data_root))] = sha256_file(path)
        return path

    def parent_frame(name):
        path = parent / "inputs" / name
        if sha256_file(path) != parent_hashes[str(path.relative_to(parent))]:
            raise ValueError("parent source changed")
        source(path)
        return pd.read_parquet(path)

    calendar_path = source(data_root / config["calendar_file"])
    sessions = pd.DatetimeIndex(json.loads(calendar_path.read_text())["sessions"])
    closing_times_path = source(data_root / config["calendar_close_file"])
    closing_times = pd.Series(json.loads(closing_times_path.read_text())["closes"])
    closing_times.index = pd.to_datetime(closing_times.index)
    closing_times = pd.to_datetime(closing_times, utc=True)
    if not closing_times.index.equals(sessions):
        raise ValueError("calendar sessions and closing timestamps disagree")
    closing_times.to_frame("close_time").to_parquet(
        base / "exchange_closes.parquet", compression="zstd"
    )
    vintages, vintage_audit = archive_observations(sources / "vintages")
    vintages.to_parquet(base / "valuation_vintages.parquet", compression="zstd", index=False)
    write_json(base / "vintage_audit.json", vintage_audit)
    spx = parent_frame("sp500_bars.parquet").close
    temperature = archive_temperature(
        spx, vintages, decision_times=closing_times, **config["vintage_settings"]
    )
    temperature.to_parquet(base / "sp500_archive_temperature.parquet", compression="zstd")
    evidence, checks = {}, []
    for asset in config["assets"]:
        setting = config["asset_settings"][asset]
        symbol = setting["symbol"]
        if setting["kind"] == "us_etf":
            bars, splits = chart_prices(
                source(sources / setting["chart"]), symbol, config["cutoff"]
            )
            if setting.get("split_proof"):
                proof = json.loads(source(sources / setting["split_proof"]).read_text())
                if (
                    len(splits) != 1
                    or splits.ratio.iloc[0] != proof["ratio"]
                    or str(splits.ex_date.iloc[0].date()) != proof["effective_date"]
                ):
                    raise ValueError("ETF split disagrees with publisher evidence")
            if setting["dividends"] == "ssga":
                actions = ssga_actions(
                    source(data_root / config["ssga_distribution_file"]), symbol, config["cutoff"]
                )
            else:
                actions = nasdaq_actions(
                    source(sources / setting["dividend_file"]),
                    symbol,
                    setting["actions_from"],
                    config["cutoff"],
                )
                if setting.get("issuer_table"):
                    issuer = issuer_table_actions(
                        source(sources / setting["issuer_table"]), symbol, config["cutoff"]
                    )
                    actions, conflicts = combine_distribution_evidence(issuer, actions)
                    conflicts.to_csv(base / f"{asset}_dividend_conflicts.csv", index=False)
                    if len(actions) != setting["expected_dividends"]:
                        raise ValueError("distribution coverage differs from reviewed source union")
            if len(splits):
                actions = validate_actions(pd.concat([actions, splits], ignore_index=True))
            check = calendar_check(bars, sessions)
            if check["missing"] or check["unexpected"]:
                raise ValueError(f"unadjudicated ETF calendar: {symbol}: {check}")
            signals = parent_frame(setting["signal_asset"] + "_signals.parquet")
            if asset == "qqq":
                adjudication_path = Path(config["calendar_adjudication_file"])
                adjudication = json.loads(adjudication_path.read_text())
                write_json(base / "calendar_adjudication.json", adjudication)
                missing = pd.Timestamp("2002-01-29")
                patch = json.loads(source(sources / "yahoo_ndx_gap.raw").read_text())["chart"][
                    "result"
                ][0]
                from quant.longterm.etf_sources import local_dates

                patch_prices = pd.Series(
                    patch["indicators"]["quote"][0]["close"], index=local_dates(patch["timestamp"])
                )
                value = round(float(patch_prices.loc[missing]), 2)
                expected = adjudication["inserted_closes"]["nasdaq100"][str(missing.date())]
                if value != expected or missing in signals.index:
                    raise ValueError("NDX repair evidence or original gap changed")
                signals.loc[missing, "close"] = value
                signals = signals.sort_index()
            signals = signals.reindex(bars.index)
            if signals.close.isna().any():
                raise ValueError("underlying index signal prices missing")
        else:
            bars = parent_frame(f"{asset}_bars.parquet")
            signals = parent_frame(f"{asset}_signals.parquet")
            actions = parent_frame(f"{asset}_actions.parquet")
            check = {"status": "frozen_parent_input"}
        bars, signals = bars.loc[: config["cutoff"]], signals.loc[: config["cutoff"]]
        actions = actions[pd.to_datetime(actions.ex_date) <= config["cutoff"]]
        for name, frame in (("bars", bars), ("signals", signals), ("actions", actions)):
            frame.to_parquet(base / f"{asset}_{name}.parquet", compression="zstd")
        val = temperature.reindex(bars.index)
        prefix = signals.iloc[:-75]
        known_vintages = vintages[
            pd.to_datetime(vintages.available_at, utc=True)
            <= closing_times.loc[closing_times.index <= prefix.index[-1]].iloc[-1]
        ]
        earlier_val = archive_temperature(
            spx.loc[: prefix.index[-1]],
            known_vintages,
            decision_times=closing_times,
            **config["vintage_settings"],
        ).reindex(prefix.index)
        for rule in config["registered_rules"][asset]:
            features = _features(signals, rule, config, val)
            earlier = _features(prefix, rule, config, earlier_val)
            pd.testing.assert_frame_equal(features.loc[earlier.index], earlier, check_exact=True)
            features.to_parquet(base / f"{asset}_{rule['id']}_features.parquet", compression="zstd")
            checks.append(dict(asset=asset, rule=rule["id"], sessions=len(earlier), exact=True))
        evidence[asset] = dict(
            symbol=symbol,
            lot=setting["lot"],
            basis="raw_ETF_with_dividend_receivables",
            has_actions=True,
            first=str(bars.index[0].date()),
            last=str(bars.index[-1].date()),
            rows=len(bars),
            actions=len(actions),
            actions_from=setting.get("actions_from", str(bars.index[0].date())),
            source=setting,
            calendar=check,
            formal_accepted=False,
        )
    write_json(base / "source_hashes.json", source_hashes)
    write_json(root / "coverage.json", evidence)
    write_json(root / "feature_prefix_checks.json", checks)
    write_json(root / "blocked_evidence.json", config["blocked_evidence"])
    return evidence


def reuse_etf_inputs(data_root: Path, root: Path, config: dict) -> dict:
    """Sensitivity studies reuse exact frozen features; only declared inputs change."""
    parent = data_root / "research" / config["frozen_etf_parent"]
    hashes = json.loads((parent / "payloads.json").read_text())
    names = [n for n in hashes if n.startswith("inputs/")]
    names += ["coverage.json", "feature_prefix_checks.json", "blocked_evidence.json"]
    for name in names:
        if sha256_file(parent / name) != hashes[name]:
            raise ValueError("frozen ETF input changed")
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(parent / name, target)
    if config.get("recompute_registered_features"):
        value = pd.read_parquet(root / "inputs" / "sp500_archive_temperature.parquet")
        checks = []
        for asset in config["assets"]:
            signals = pd.read_parquet(root / "inputs" / f"{asset}_signals.parquet")
            for rule in config["registered_rules"][asset]:
                features = _features(signals, rule, config, value.reindex(signals.index))
                past = signals.iloc[:-75]
                earlier = _features(past, rule, config, value.reindex(past.index))
                pd.testing.assert_frame_equal(
                    features.loc[earlier.index], earlier, check_exact=True
                )
                features.to_parquet(
                    root / "inputs" / f"{asset}_{rule['id']}_features.parquet", compression="zstd"
                )
                checks.append(dict(asset=asset, rule=rule["id"], sessions=len(earlier), exact=True))
        write_json(root / "feature_prefix_checks.json", checks)
    changes = []
    for override in config.get("input_overrides", []):
        path = root / "inputs" / f"{override['asset']}_{override['table']}.parquet"
        frame = pd.read_parquet(path)
        column, date = override["column"], pd.Timestamp(override["date"])
        mask = frame.index == date if override["table"] == "bars" else frame.ex_date == date
        if mask.sum() != 1:
            raise ValueError("source alternative is not a unique observation")
        old, new = override["expected"], override["value"]
        if column == "pay_date":
            old, new = pd.Timestamp(old), pd.Timestamp(new)
        if frame.loc[mask, column].iloc[0] != old:
            raise ValueError("source alternative no longer matches reviewed evidence")
        frame.loc[mask, column] = new
        if override["table"] == "actions":
            frame = validate_actions(frame)
        frame.to_parquet(path, compression="zstd")
        changes.append(override)
    write_json(root / "inputs" / "declared_source_alternatives.json", changes)
    write_json(
        root / "inputs" / "frozen_parent.json",
        {"run": config["frozen_etf_parent"], "verified": {n: hashes[n] for n in names}},
    )
    return json.loads((root / "coverage.json").read_text())
