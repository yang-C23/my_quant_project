"""Auditable platform operations; imports are lazy to keep help/doctor lightweight."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

app = typer.Typer(add_completion=False, help="Trusted data snapshots and long-term research.")


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
