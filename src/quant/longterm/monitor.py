"""Fail-closed daily shadow monitoring; no broker or messaging side effects."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant.config import Settings, load_config
from quant.data.catalog import DataCatalog
from quant.data.snapshots import SnapshotStore, utc_now, write_json
from quant.longterm.features import price_features
from quant.longterm.research import _load_asset, valuation_features


def daily_monitor(
    settings: Settings,
    config_path: Path,
    *,
    now: str | None = None,
    refresh_status: dict | None = None,
) -> dict:
    """Record real observations once per actual data date; historical replay is not a shadow day."""
    observed_at = pd.Timestamp(now or utc_now())
    if observed_at.tzinfo is None:
        raise ValueError("monitor time must include timezone")
    observed_at = observed_at.tz_convert("UTC")
    config = load_config(config_path)
    catalog = DataCatalog(settings.data_root)
    store = SnapshotStore(settings.data_root)
    snapshot_id = store.current()
    global_errors = []
    try:
        versions = {m["dataset"]: m["version"] for m in catalog.list_datasets()}
        if not snapshot_id or not store.verify(snapshot_id)["ok"]:
            global_errors.append("snapshot_missing_or_integrity_failed")
    except Exception as exc:
        versions = {}
        global_errors.append(f"input_registry_unavailable: {type(exc).__name__}: {exc}")
    directory = settings.data_root / "monitor"
    directory.mkdir(parents=True, exist_ok=True)
    promotion_path = directory / "promoted_rules.json"
    # Promotion is a research deliverable, not a switch that bypasses data acceptance.
    promoted = json.loads(promotion_path.read_text()) if promotion_path.exists() else {}
    messages = []
    for asset in config["universe"]:
        reasons = list(global_errors)
        last_date, observations = None, {}
        if not promoted.get(asset["id"]):
            reasons.append("strategy_not_promoted_by_verified_out_of_sample_research")
        try:
            if global_errors:
                raise ValueError("unverified input registry or snapshot")
            bars, evidence = _load_asset(
                settings, asset, catalog, versions, snapshot_id=snapshot_id
            )
            timezone, close_hour = (
                ("America/New_York", 16) if asset["market"] == "US" else ("Asia/Shanghai", 15)
            )
            local_now = observed_at.tz_convert(timezone)
            completed = bars.index < local_now.tz_localize(None).normalize()
            if local_now.hour >= close_hour:
                completed |= bars.index == local_now.tz_localize(None).normalize()
            bars = bars.loc[completed]
            if bars.empty:
                raise ValueError("no completed local session")
            last_date = str(bars.index[-1].date())
            age = (local_now.tz_localize(None).normalize() - bars.index[-1]).days
            # A conservative wall-clock cap; verified venue calendar is still required below.
            if age > 4:
                reasons.append(f"stale_prices_{age}_calendar_days")
            if not evidence.get("formal_accepted", False):
                reasons.append("source_quality_or_pit_or_retention_not_accepted")
            if "ETF" in evidence.get("basis", "") and not evidence.get(
                "corporate_actions_complete", False
            ):
                raise ValueError("ETF_corporate_actions_incomplete_no_raw_price_panic_signal")
            panic = config.get("strategy_matrix", {}).get("panic", {})
            feature = price_features(
                bars,
                **{
                    key: panic[key]
                    for key in ("drawdown", "sigma", "confirmation", "event_window")
                    if key in panic
                },
            ).iloc[-1]
            observations = {
                "drawdown_252": None
                if pd.isna(feature.drawdown_252)
                else float(feature.drawdown_252),
                "panic": bool(feature.panic),
                "stabilized": bool(feature.stabilized),
                "j": None if pd.isna(feature.j) else float(feature.j),
            }
            try:
                percentile = valuation_features(asset, bars, catalog, versions, "pe", 10).iloc[-1]
                if pd.isna(percentile):
                    reasons.append("PE_10y_history_or_warmup_or_publication_evidence_missing")
                else:
                    observations["pe_percentile_10y"] = float(percentile)
            except (ValueError, FileNotFoundError):
                reasons.append("PE_10y_history_or_warmup_or_publication_evidence_missing")
        except Exception as exc:
            reasons.append(f"source_unavailable: {exc}")
        reasons.extend(
            [
                "verified_forward_trading_calendar_missing",
                "actual_account_and_execution_state_not_reconciled",
            ]
        )
        messages.append(
            {
                "asset": asset["id"],
                "name": asset["name"],
                "strategy_version": config["protocol_version"],
                "status": "暂停评估",
                "data_date": last_date,
                "snapshot_id": snapshot_id,
                "observations_only": observations,
                "reasons": reasons,
                "budget": {"account_type": "example_not_actual_holdings", **config["funding"]},
                "suggested_amount": None,
                "next_tradable_at": None,
                "invalidated_by": [
                    "new_data_revision",
                    "stale_or_missing_dependency",
                    "unreconciled_account",
                ],
                "orders_sent": False,
            }
        )
    report = {
        "observed_at": observed_at.isoformat(),
        "snapshot_id": snapshot_id,
        "catalog_versions": versions,
        "refresh_status": refresh_status,
        "mode": "shadow",
        "notifications": messages,
        "external_messages_sent": False,
    }
    identifier = observed_at.strftime("%Y%m%dT%H%M%S%fZ")
    write_json(directory / "daily" / f"{identifier}.json", report)
    write_json(directory / "latest.json", report)
    state_path = directory / "shadow.json"
    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {
            "started_at": observed_at.isoformat(),
            "required_trading_days": 20,
            "observed_sessions": {},
            "passed": False,
            "status": "in_progress_no_trade_recommendations",
        }
    )
    for item in messages:
        if item["data_date"]:
            dates = set(state["observed_sessions"].get(item["asset"], []))
            # Old/replayed sessions never advance the forward shadow period.
            if pd.Timestamp(item["data_date"]).date() >= pd.Timestamp(state["started_at"]).date():
                dates.add(item["data_date"])
            state["observed_sessions"][item["asset"]] = sorted(dates)
    state["last_observed_at"] = observed_at.isoformat()
    state["observed_session_counts"] = {k: len(v) for k, v in state["observed_sessions"].items()}
    state["passed"] = (
        False  # A formal acceptance review, including failures, is required after 20 days.
    )
    write_json(state_path, state)
    return {
        "directory": str(directory),
        "snapshot_id": snapshot_id,
        "paused": len(messages),
        "actionable": 0,
        "shadow": state,
    }
