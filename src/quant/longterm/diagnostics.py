"""Comparable price-only diagnostics and an independent journal/unitization audit."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import json
import math
from pathlib import Path

import pandas as pd

from quant.config import Settings
from quant.data.catalog import DataCatalog
from quant.data.snapshots import SnapshotStore, sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.engine import Backtest, Strategy, run_strategy
from quant.longterm.features import price_features
from quant.longterm.ledger import Costs, dec
from quant.longterm.research import _load_asset, save_result


def drawdown_episode(nav: pd.Series) -> dict:
    """Locate the worst peak-to-trough loss, including the initial NAV of one."""
    if nav.empty or nav.isna().any() or (nav <= 0).any():
        raise ValueError("positive nonmissing NAV required")
    high = nav.cummax().clip(lower=1)
    losses = nav / high - 1
    trough = losses.idxmin()
    level = float(high.loc[trough])
    candidates = nav.loc[:trough][nav.loc[:trough] >= level]
    peak = candidates.index[-1] if len(candidates) else None
    recovered = nav.loc[trough:][nav.loc[trough:] >= level]
    recovery = recovered.index[0] if len(recovered) else None
    return {
        "max_drawdown": float(losses.loc[trough]),
        "peak_date": str(peak.date()) if peak is not None else None,
        "trough_date": str(trough.date()),
        "recovery_date": str(recovery.date()) if recovery is not None else None,
        "peak_to_recovery_days": (recovery - peak).days
        if peak is not None and recovery is not None
        else None,
        "unrecovered": recovery is None,
    }


def verify_price_ledger(result: Backtest, close: pd.Series) -> dict:
    """Rebuild cash, holdings and fund units without calling Ledger/performance.

    This oracle deliberately supports only same-close executions without company
    actions or interest. It fails on other journals instead of silently ignoring
    their cash flows. Contributions buy units at the pre-flow NAV; they never
    increase the unit price. Core/tactical sleeves retain separate cent rounding.
    """
    journal, daily = result.journal.copy(), result.daily
    if not set(journal["kind"]).issubset({"deposit", "buy", "sell"}):
        raise ValueError("oracle requires price-only deposit/buy/sell journals")
    if not close.index.is_unique or daily.index.difference(close.index).size:
        raise ValueError("all valuation dates must have a unique close")
    if daily["receivable"].abs().max() != 0:
        raise ValueError("oracle cannot value dividend receivables")
    journal["sleeve"] = journal.get("sleeve", "single")
    state = {name: [Decimal(0), Decimal(0)] for name in journal["sleeve"].unique()}
    groups: dict[pd.Timestamp, list[dict]] = {}
    for entry in journal.to_dict("records"):
        groups.setdefault(pd.Timestamp(entry["date"]), []).append(entry)
    if set(groups) - set(daily.index):
        raise ValueError("journal contains dates outside the report")
    units = Decimal(0)
    errors = dict.fromkeys(
        ("cash", "shares", "equity", "pre_flow_equity", "external_flow", "nav"), 0.0
    )
    cash_flows = []

    def cents(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    for date, row, raw_price in zip(
        daily.index, daily.to_dict("records"), close.reindex(daily.index).to_numpy()
    ):
        price = Decimal(str(raw_price))
        before = sum((cents(cash + shares * price) for cash, shares in state.values()), Decimal(0))
        group = groups.get(date, ())
        flow = sum(
            (entry["amount"] for entry in group if entry["kind"] == "deposit"),
            Decimal(0),
        )
        subscription_nav = before / units if units else Decimal(1)
        units += flow / subscription_nav
        # Contributions occur before any same-close execution in every sleeve.
        for entry in group:
            if entry["kind"] == "deposit":
                state[entry["sleeve"]][0] += entry["amount"]
        for entry in group:
            if entry["kind"] == "deposit":
                continue
            cash, shares = state[entry["sleeve"]]
            direction = 1 if entry["kind"] == "buy" else -1
            if cents(entry["quantity"] * entry["price"]) != entry["notional"]:
                raise AssertionError("fill notional disagrees with quantity and fill price")
            state[entry["sleeve"]] = [
                cash - direction * entry["notional"] - entry["fee"],
                shares + direction * entry["quantity"],
            ]
        equity = sum((cents(cash + shares * price) for cash, shares in state.values()), Decimal(0))
        expected = {
            "cash": float(sum(cash for cash, _ in state.values())),
            "shares": float(sum(shares for _, shares in state.values())),
            "equity": float(equity),
            "pre_flow_equity": float(before),
            "external_flow": float(flow),
            "nav": float(equity / units) if units else 1.0,
        }
        for key, value in expected.items():
            actual = row["twr_nav" if key == "nav" else key]
            if not math.isfinite(actual) or not math.isfinite(value):
                raise AssertionError(f"independent journal audit found nonfinite {key}")
            error = abs(value - actual)
            if key == "nav":
                error /= max(abs(value), 1)
            errors[key] = max(errors[key], error)
        if flow:
            cash_flows.append((date, -float(flow)))
    cash_flows.append((daily.index[-1], float(equity)))
    rate = result.metrics["xirr"]
    if rate is None or not math.isfinite(rate) or rate <= -1:
        raise ValueError("reported XIRR cannot be checked within a finite numerical domain")
    first = cash_flows[0][0]
    residual = sum(
        amount / (1 + rate) ** ((date - first).days / 365.2425) for date, amount in cash_flows
    )
    normalized_residual = abs(residual) / sum(abs(amount) for _, amount in cash_flows)
    if any(value > 1e-8 for value in errors.values()) or normalized_residual > 1e-8:
        raise AssertionError(f"independent journal audit failed: {errors}, xirr={residual}")
    return {"ok": True, "maximum_errors": errors, "xirr_relative_residual": normalized_residual}


def review_results(
    settings: Settings,
    reference_run: Path,
    *,
    start: str = "2016-10-20",
    end: str = "2026-10-19",
) -> dict:
    """Freeze a common-window comparison without changing any strategy rules."""
    reference_run = reference_run.resolve()
    original = json.loads((reference_run / "registration.json").read_text())
    config = original["config"]
    if config["execution"]["cash_yield"] != 0:
        raise ValueError("this price-only journal oracle requires zero cash interest")
    store = SnapshotStore(settings.data_root)
    snapshot_id = original["snapshot_id"]
    if not store.verify(snapshot_id)["ok"]:
        raise ValueError("reference snapshot failed checksum verification")
    if (
        sha256_file(store.path(snapshot_id) / "manifest.json")
        != original["snapshot_manifest_sha256"]
    ):
        raise ValueError("snapshot manifest differs from original research")
    code = code_revision()
    for path in (
        "src/quant/longterm/engine.py",
        "src/quant/longterm/features.py",
        "src/quant/longterm/ledger.py",
        "src/quant/backtest/metrics.py",
    ):
        if code["sources"][path] != original["code"]["sources"][path]:
            raise ValueError(f"original strategy source changed: {path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = settings.data_root / "audits" / f"strategy-review-{stamp}"
    target.mkdir(parents=True)
    write_json(
        target / "registration.json",
        {
            "reference_run": str(reference_run),
            "reference_registration_sha256": sha256_file(reference_run / "registration.json"),
            "snapshot_id": snapshot_id,
            "snapshot_manifest_sha256": original["snapshot_manifest_sha256"],
            "catalog_versions": original["catalog_versions"],
            "config": config,
            "code": code,
            "start": start,
            "end": end,
            "execution": "next_close",
            "status": "exploratory_price_only_no_selection",
            "rules_unchanged": True,
            "additional_control": "dca_core50",
            "hypotheses": ["lump_sum", "dca", "kdj", "kdj_core50", "dca_core50"],
        },
    )
    catalog = DataCatalog(settings.data_root)
    costs = Costs(
        **{
            key: dec(config["execution"][key])
            for key in (
                "commission_rate",
                "minimum_commission",
                "slippage_bps",
                "dividend_tax_rate",
            )
        }
    )
    rows, blocked, old_episodes = [], [], []
    old = pd.read_parquet(reference_run / "results.parquet")
    for asset in config["universe"]:
        if asset.get("style") == "dividend_lowvol" or asset["id"] in {"star50", "star100"}:
            continue
        bars, evidence = _load_asset(
            settings, asset, catalog, original["catalog_versions"], snapshot_id=snapshot_id
        )
        if bars.index[0] > pd.Timestamp(start) or bars.index[-1] < pd.Timestamp(end):
            raise ValueError(f"incomplete common window: {asset['id']}")
        features = price_features(bars)
        for experiment in ("lump_sum", "dca", "kdj", "kdj_core50", "dca_core50"):
            name = experiment.removesuffix("_core50")
            if name == "kdj" and features["j"].isna().all():
                blocked.append(
                    {"asset": asset["id"], "experiment": experiment, "reason": "no_OHLC"}
                )
                continue
            result = run_strategy(
                bars,
                features,
                Strategy(
                    name=name,
                    **config["funding"],
                    core_fraction=0.5 if experiment.endswith("_core50") else 0,
                ),
                symbol=asset["id"],
                start=start,
                end=end,
                costs=costs,
                lot=dec(config["execution"]["index_proxy_lot"]),
                price_basis="price_only",
                execution="next_close",
            )
            audit = verify_price_ledger(result, bars["close"])
            destination = target / asset["id"] / experiment
            save_result(result, destination)
            write_json(destination / "independent_audit.json", audit)
            write_json(destination / "evidence.json", evidence)
            episode = drawdown_episode(result.daily["twr_nav"])
            rows.append(
                {
                    "asset": asset["id"],
                    "name": asset["name"],
                    "experiment": experiment,
                    **result.metrics,
                    **episode,
                    "ending_budget": float(result.daily["remaining_budget"].iloc[-1]),
                    "cash_outside_principal_budget": float(
                        result.daily["cash"].iloc[-1] - result.daily["remaining_budget"].iloc[-1]
                    ),
                    "journal_audit_ok": audit["ok"],
                }
            )
        historical = old[
            old["asset"].eq(asset["id"])
            & old["experiment"].eq("dca")
            & old["status"].eq("exploratory_price_only")
            & old["contains_prelaunch"].eq(False)
        ].sort_values(["start", "end"], ascending=[True, False])
        selected = historical.iloc[0]
        old_daily = pd.read_parquet(
            reference_run / asset["id"] / "dca" / selected["window"] / "daily.parquet"
        )
        old_episodes.append(
            {
                "asset": asset["id"],
                "window": selected["window"],
                "investment_start": selected["start"],
                **drawdown_episode(old_daily["twr_nav"]),
            }
        )
    frame = pd.DataFrame(rows)
    # Equal contributions within a market/asset are required for a fair rule comparison.
    for _, group in frame.groupby("asset"):
        if group["contributed"].nunique() != 1:
            raise AssertionError("strategies have inconsistent external contributions")
    frame.to_csv(target / "comparison.csv", index=False)
    frame.to_parquet(target / "comparison.parquet", compression="zstd")
    write_json(target / "blocked.json", blocked)
    write_json(target / "original_drawdowns.json", old_episodes)
    report = {
        "path": str(target),
        "rows": len(frame),
        "blocked": len(blocked),
        "all_journal_audits_passed": bool(frame["journal_audit_ok"].all()),
        "comparison_sha256": sha256_file(target / "comparison.parquet"),
        "status": "exploratory_price_only_no_investment_recommendation",
    }
    write_json(target / "summary.json", report)
    return report
