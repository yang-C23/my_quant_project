"""Auditable platform operations; imports are lazy to keep help/doctor lightweight."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

app = typer.Typer(add_completion=False, help="Trusted data snapshots and long-term research.")


@app.command("refresh-shiller-research")
def refresh_shiller_research_cmd(
    source: Path,
    destination: Path,
    version: str | None = None,
    replay_run: Path | None = None,
) -> None:
    """Recompute every prespecified Shiller proxy on a newly pinned monthly vintage."""
    from quant.config import get_settings
    from quant.longterm.valuation_refresh import run_shiller_refresh

    output(
        run_shiller_refresh(
            get_settings(), source, destination, version=version, replay_run=replay_run
        )
    )


@app.command("fetch-shiller")
def fetch_shiller_cmd(cached_dir: Path | None = None) -> None:
    """Append the maintained author's monthly workbook without overwriting old vintages."""
    from quant.config import get_settings
    from quant.data.free_history import ingest_maintained_shiller

    manifest = ingest_maintained_shiller(get_settings().data_root, cached_dir=cached_dir)
    output(
        {key: manifest[key] for key in ("dataset", "version", "rows", "first_date", "last_date")}
    )


@app.command("audit-cftc-releases")
def audit_cftc_releases_cmd(
    source: Path,
    destination: Path,
    config: Path = Path("configs/cftc_release_audit.yaml"),
) -> None:
    """Compare registered CFTC policies with known reporting interruptions excluded."""
    from quant.config import get_settings
    from quant.longterm.release_audit import run_release_audit

    output(run_release_audit(get_settings(), source, config, destination))


@app.command("audit-fund-reports")
def audit_fund_reports_cmd(source: Path, documents: Path, destination: Path) -> None:
    """Reconcile annual issuer disclosures and preserve historical industry weights."""
    from quant.config import get_settings
    from quant.longterm.fund_review import review_issuer_reports

    output(review_issuer_reports(get_settings().data_root, source, documents, destination))


@app.command("cash-pool-extensions")
def cash_pool_extensions_cmd(
    source: Path,
    config: Path = Path("configs/cash_pool_extensions.yaml"),
    replay_run: Path | None = None,
) -> None:
    """Run registered style, currency and first-party pressure extensions."""
    from quant.config import get_settings
    from quant.longterm.pool_extensions import run_pool_extensions

    output(run_pool_extensions(get_settings(), source, config, replay_run=replay_run))


@app.command("fetch-pressure")
def fetch_pressure_cmd(end: str, cached_cboe_dir: Path | None = None) -> None:
    """Acquire first-party Shanghai financing and Cboe pressure reference histories."""
    from quant.config import get_settings
    from quant.data.pressure import fetch_pressure_data

    output(fetch_pressure_data(get_settings().data_root, end=end, cached_cboe_dir=cached_cboe_dir))


@app.command("analyze-cash-pool")
def analyze_cash_pool_cmd(
    source: Path,
    destination: Path,
    config: Path = Path("configs/cash_pool_extensions.yaml"),
    corrections: Path | None = None,
) -> None:
    """Analyze all saved windows and crisis clusters without selecting only winners."""
    from quant.config import load_config
    from quant.longterm.pool_analysis import analyze_pool_run

    output(analyze_pool_run(source, load_config(config), destination, corrections=corrections))


@app.command("issuer-evidence")
def issuer_evidence_cmd(
    declaration: Path,
    nav_file: Path | None = None,
) -> None:
    """Import reviewed issuer actions and reconcile every official NAV observation."""
    from quant.config import get_settings, load_config
    from quant.data.issuer_funds import fetch_issuer_nav, ingest_reviewed_actions

    settings = get_settings()
    evidence = load_config(declaration)
    nav = fetch_issuer_nav(
        settings.data_root,
        evidence["symbol"],
        end=evidence["coverage_end"],
        cached_file=nav_file,
    )
    actions = ingest_reviewed_actions(settings.data_root, evidence)
    output(
        {
            "nav": {"dataset": nav["dataset"], "version": nav["version"], "rows": nav["rows"]},
            "actions": actions,
        }
    )


@app.command("analyze-cash-pool-extensions")
def analyze_cash_pool_extensions_cmd(source: Path, destination: Path) -> None:
    """Compare every style/FX/factor extension on matched cash-flow calendars."""
    from quant.longterm.pool_analysis import analyze_pool_extensions

    output(analyze_pool_extensions(source, destination))


@app.command("fetch-history")
def fetch_history_cmd(
    first_cftc_year: int = 2006,
    last_cftc_year: int = 2026,
    first_cffex_month: str | None = None,
    last_cffex_month: str | None = None,
    workers: int = 2,
) -> None:
    """Acquire explicitly bounded free first-party archives without paid subscriptions."""
    import pandas as pd

    from quant.config import get_settings
    from quant.data.free_history import acquire_archives

    if first_cftc_year > last_cftc_year:
        raise typer.BadParameter("first year must not exceed last year")
    months = []
    if bool(first_cffex_month) != bool(last_cffex_month):
        raise typer.BadParameter("provide both CFFEX month bounds")
    if first_cffex_month:
        start = pd.to_datetime(first_cffex_month, format="%Y%m")
        end = pd.to_datetime(last_cffex_month, format="%Y%m")
        if start > end:
            raise typer.BadParameter("first month must not exceed last month")
        months = pd.period_range(start, end, freq="M").strftime("%Y%m").tolist()
    output(
        acquire_archives(
            get_settings().data_root,
            cftc_years=list(range(first_cftc_year, last_cftc_year + 1)),
            cffex_months=months,
            workers=workers,
        )
    )


@app.command("fetch-public")
def fetch_public_cmd(baostock: bool = False) -> None:
    """Acquire free public references and record missing access/coverage explicitly."""
    from quant.config import get_settings
    from quant.data.providers import fetch_public

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    output(fetch_public(get_settings().data_root, include_baostock=baostock))


@app.command("sources")
def sources_cmd() -> None:
    """List immutable public dataset versions and their quality/permission status."""
    from quant.config import get_settings
    from quant.data.catalog import DataCatalog

    output(DataCatalog(get_settings().data_root).list_datasets())


def output(value: object) -> None:
    """Render machine-readable UTF-8 results."""
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False))


@app.command("audit")
def audit_cmd() -> None:
    """Inventory code, dependencies, datasets and all old result artifacts."""
    from quant.config import get_settings
    from quant.data.audit import audit_project

    output(audit_project(get_settings(), Path(__file__).resolve().parents[2]))


@app.command("tdx-update")
def tdx_update_cmd(
    workers: int = 4,
    qlib: bool = True,
    publish: bool = True,
    resume: str | None = None,
) -> None:
    """Build and validate a fresh snapshot; publish atomically after completion."""
    from quant.config import get_settings
    from quant.etl.restart import update_snapshot

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    output(
        update_snapshot(
            get_settings(), workers=workers, build_qlib=qlib, publish=publish, resume=resume
        )
    )


@app.command("verify")
def verify_cmd(snapshot_id: str) -> None:
    """Verify every payload checksum in an immutable snapshot."""
    from quant.config import get_settings
    from quant.data.snapshots import SnapshotStore

    result = SnapshotStore(get_settings().data_root).verify(snapshot_id)
    output(result)
    if not result["ok"]:
        raise typer.Exit(1)


@app.command("activate")
def activate_cmd(snapshot_id: str) -> None:
    """Select a verified snapshot, or 'legacy' to restore the original dataset."""
    from quant.config import get_settings
    from quant.data.snapshots import SnapshotStore

    store = SnapshotStore(get_settings().data_root)
    with store.writer_lock():
        store.activate(snapshot_id)
    output({"active_snapshot": store.current() or "legacy"})


@app.command("research")
def research_cmd(
    config: Path = Path("configs/longterm.yaml"),
    exploratory: bool = False,
    replay_run: Path | None = None,
) -> None:
    """Run registered research; explicit exploratory mode permits price-only diagnostics."""
    from quant.config import get_settings
    from quant.longterm.research import run_research

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    output(run_research(get_settings(), config, exploratory=exploratory, replay_run=replay_run))


@app.command("crosscheck")
def crosscheck_cmd() -> None:
    """Compare all available alternative-source prices and activity units."""
    from quant.config import get_settings
    from quant.data.reconcile import crosscheck

    output(crosscheck(get_settings()))


@app.command("review-results")
def review_results_cmd(
    reference_run: Path,
    start: str = "2016-10-20",
    end: str = "2026-10-19",
) -> None:
    """Audit journals and compare unchanged rules on a common price-index window."""
    from quant.config import get_settings
    from quant.longterm.diagnostics import review_results

    output(review_results(get_settings(), reference_run, start=start, end=end))


@app.command("cash-pool-research")
def cash_pool_research_cmd(
    reference_run: Path,
    config: Path = Path("configs/cash_pool.yaml"),
    workers: int = 2,
    replay_run: Path | None = None,
    resume_run: Path | None = None,
) -> None:
    """Run the frozen cash-pool/stress study and retain all outcomes and paired controls."""
    from quant.config import get_settings
    from quant.longterm.pool_research import run_pool_research

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    output(
        run_pool_research(
            get_settings(),
            config,
            reference_run,
            workers=workers,
            replay_run=replay_run,
            resume_run=resume_run,
        )
    )


@app.command("backup")
def backup_cmd(snapshot_id: str, restore: bool = True) -> None:
    """Back up a sealed snapshot and optionally perform a complete isolated restore drill."""
    from quant.config import get_settings
    from quant.data.recovery import backup_snapshot, restore_drill

    root = get_settings().data_root
    result = {"backup": backup_snapshot(root, snapshot_id)}
    if restore:
        result["restore_drill"] = restore_drill(root, snapshot_id)
    output(result)


@app.command("daily")
def daily_cmd(
    config: Path = Path("configs/longterm.yaml"),
    refresh_public: bool = False,
    update_tdx: bool = False,
) -> None:
    """Refresh optional inputs and write local shadow alerts; never place orders."""
    from quant.config import get_settings
    from quant.data.providers import fetch_public
    from quant.etl.restart import update_snapshot
    from quant.longterm.monitor import daily_monitor

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    refresh = {}
    if update_tdx:
        try:
            refresh["tdx"] = update_snapshot(settings, workers=4)
        except Exception as exc:
            refresh["tdx"] = {"status": "failed", "reason": str(exc)}
    if refresh_public:
        try:
            refresh["public"] = fetch_public(settings.data_root)
        except Exception as exc:
            refresh["public"] = {"status": "failed", "reason": str(exc)}
    output(daily_monitor(settings, config, refresh_status=refresh))


@app.command("fetch-derivatives")
def derivatives_cmd(month: str = "202609", year: int = 2025) -> None:
    """Fetch official contract and positioning archives as individually pinned datasets."""
    from quant.config import get_settings
    from quant.data.derivatives import fetch_derivatives

    output(fetch_derivatives(get_settings().data_root, month=month, year=year))


@app.command("fetch-etf-day")
def etf_day_cmd(date: str) -> None:
    """Acquire one CN ETF trading session through the dedicated bounded vendor API."""
    from quant.config import get_settings
    from quant.data.catalog import DataCatalog
    from quant.data.providers import fetch_baostock_etf_day

    output(fetch_baostock_etf_day(DataCatalog(get_settings().data_root), date))
