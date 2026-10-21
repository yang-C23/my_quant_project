from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version as package_version
import subprocess
import sys
from typing import Annotated

import typer
from quant.platform_cli import app as platform_app

app = typer.Typer(add_completion=False)
etl_app = typer.Typer(add_completion=False, help="Data platform ETL commands.")
dump_app = typer.Typer(add_completion=False, help="Qlib dump commands.")
backtest_app = typer.Typer(add_completion=False, help="Portfolio backtest commands.")
app.add_typer(etl_app, name="etl")
app.add_typer(dump_app, name="dump")
app.add_typer(backtest_app, name="backtest")
app.add_typer(platform_app, name="platform")


@app.command("doctor")
def doctor_cmd() -> None:
    """Validate the worktree import and show nonsensitive runtime provenance."""
    import json
    from pathlib import Path
    import quant
    from quant.config import get_settings

    expected = Path(os.environ.get("QUANT_PROJECT_ROOT", Path.cwd())).resolve()
    actual = Path(quant.__file__).resolve()
    ok = actual == expected / "src" / "quant" / "__init__.py"
    mismatches = []
    lock = expected / "requirements-lock.txt"
    if lock.exists():
        for line in lock.read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            name, pinned = line.split("==", 1)
            try:
                installed = package_version(name)
            except PackageNotFoundError:
                installed = "missing"
            if installed != pinned:
                mismatches.append({"package": name, "expected": pinned, "installed": installed})
    else:
        mismatches.append({"lock": "missing"})
    ok = ok and not mismatches
    settings = get_settings()
    typer.echo(
        json.dumps(
            {
                "ok": ok,
                "dependency_mismatches": mismatches,
                "python": sys.executable,
                "import_path": str(actual),
                "expected_root": str(expected),
                "data_root": str(settings.data_root),
                "staging": str(settings.staging_dir),
                "tdx_home_exists": settings.tdx_home.exists(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not ok:
        raise typer.Exit(1)


_ETL_STEPS = ("daily", "gbbq", "securities", "blocks", "derive", "flags")
_ETL_STEP_ALIASES = {"meta": ("gbbq", "securities", "blocks", "flags")}


def get_version() -> str:
    """Return the installed package version."""
    try:
        return package_version("my-quant")
    except PackageNotFoundError:
        return "0.1.0"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(get_version())
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            help="Show the package version and exit.",
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Command-line entry point for my-quant."""
    if os.environ.get("QUANT_COMPUTE_MANAGED") == "1":
        from quant.compute import configure_native_threads

        configure_native_threads()


@etl_app.command("full")
def etl_full(
    steps: Annotated[
        str, typer.Option(help=f"Comma-separated steps, subset of {','.join(_ETL_STEPS)}.")
    ] = "daily",
    workers: Annotated[
        int | None, typer.Option(help="Parallel parse workers (default: settings.etl_workers).")
    ] = None,
    mirror: Annotated[
        bool, typer.Option("--mirror/--no-mirror", help="Refresh the local TDX mirror first.")
    ] = True,
) -> None:
    """Full ETL load: mirror TDX data and build Parquet staging tables."""
    from quant.config import get_settings
    from quant.etl.adjust import build_adjust_staging
    from quant.etl.basics import build_basics_staging
    from quant.etl.mirror import extract_zip_baseline, mirror_vipdoc
    from quant.etl.staging import (
        build_blocks_staging,
        build_daily_staging,
        build_flags_staging,
        build_gbbq_staging,
        build_securities_staging,
    )

    settings = get_settings()
    if (settings.active_data_dir / "manifest.json").exists():
        raise typer.BadParameter("sealed snapshot: use scripts/quant update to build a new version")
    requested = [s.strip() for s in steps.split(",") if s.strip()]
    valid_steps = _ETL_STEPS + tuple(_ETL_STEP_ALIASES)
    unknown = [s for s in requested if s not in valid_steps]
    if unknown:
        typer.echo(f"unknown steps: {unknown}; valid: {valid_steps}", err=True)
        raise typer.Exit(code=2)

    expanded: list[str] = []
    aliased_steps: set[str] = set()
    for step in requested:
        alias_steps = _ETL_STEP_ALIASES.get(step)
        if alias_steps is None:
            expanded.append(step)
        else:
            expanded.extend(alias_steps)
            aliased_steps.update(alias_steps)

    if "daily" in expanded:
        if mirror:
            if settings.tdx_zip is not None and settings.tdx_zip.exists():
                zstats = extract_zip_baseline(settings.tdx_zip, settings.mirror_dir)
                typer.echo(
                    f"zip baseline: {zstats.files} files, {zstats.bytes / 1e6:.1f} MB, "
                    f"{zstats.seconds:.1f}s"
                )
            mstats = mirror_vipdoc(settings.tdx_home, settings.mirror_dir)
            typer.echo(
                f"mirror: {mstats.files} files, {mstats.bytes / 1e6:.1f} MB, {mstats.seconds:.1f}s"
            )
        sstats = build_daily_staging(
            settings.mirror_dir,
            settings.staging_dir,
            workers=workers or settings.etl_workers,
        )
        typer.echo(
            f"staging daily: {sstats.rows} rows from {sstats.files_total} files "
            f"({sstats.files_failed} failed, {sstats.records_skipped} records skipped, "
            f"{sstats.rows_deduped} overlap rows deduped) "
            f"in {sstats.seconds:.1f}s | by exchange: {sstats.by_exchange}"
        )

    if "gbbq" in expanded:
        rows = build_gbbq_staging(settings.tdx_home, settings.staging_dir)
        typer.echo(f"staging gbbq: {rows} rows")

    if "securities" in expanded:
        rows = build_securities_staging(settings.staging_dir)
        typer.echo(f"staging securities: {rows} rows")

    if "blocks" in expanded:
        rows = build_blocks_staging(settings.tdx_home, settings.staging_dir)
        typer.echo(f"staging blocks/holidays: {rows} rows")

    if "derive" in expanded:
        basics_rows = build_basics_staging(settings.staging_dir)
        adjust_rows = build_adjust_staging(settings.staging_dir)
        typer.echo(f"staging basics: {basics_rows} rows")
        typer.echo(f"staging adjust: {adjust_rows} rows")

    if "flags" in expanded:
        try:
            rows = build_flags_staging(settings.staging_dir)
        except FileNotFoundError as exc:
            if "flags" in aliased_steps and "basics" in str(exc):
                typer.echo("staging flags: skipped (requires basics from TASK-012)")
            else:
                raise
        else:
            typer.echo(f"staging flags: {rows} rows")


@dump_app.command("cn-daily")
def dump_cn_daily_cmd(
    symbols: Annotated[
        str | None,
        typer.Option(help="Optional comma-separated internal symbols, e.g. sh600000,sz000001."),
    ] = None,
) -> None:
    """Rebuild qlib cn_daily bin data from staging."""
    from quant.config import get_settings
    from quant.etl.qlib_dump import dump_cn_daily

    settings = get_settings()
    if (settings.active_data_dir / "manifest.json").exists():
        raise typer.BadParameter("sealed snapshot: rebuild Qlib through scripts/quant update")
    selected = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    stats = dump_cn_daily(settings.staging_dir, settings.qlib_cn_daily_uri, selected)
    typer.echo(
        f"qlib cn_daily: {stats.rows} rows, {stats.instruments} instruments, "
        f"{stats.fields} fields in {stats.seconds:.1f}s"
    )


def _rerun_with_hash_seed_zero(command_args: list[str]) -> None:
    """Restart hash-sensitive qlib commands under a deterministic hash seed."""
    if os.environ.get("PYTHONHASHSEED") == "0":
        return
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    completed = subprocess.run([sys.executable, "-m", "quant.cli", *command_args], env=env)
    raise typer.Exit(code=completed.returncode)


@backtest_app.command("topk")
def backtest_topk_cmd(config_path: str) -> None:
    """Run a qlib TopkDropout portfolio backtest."""
    _rerun_with_hash_seed_zero(["backtest", "topk", config_path])

    from quant.backtest.qlib_topk import run_topk_backtest

    result = run_topk_backtest(config_path)
    typer.echo(f"mlflow_run_id: {result.mlflow_run_id}")
    for name, value in sorted(result.metrics.items()):
        typer.echo(f"{name}: {value:.12g}")
    for name, path in sorted(result.report_paths.items()):
        typer.echo(f"{name}: {path}")


@app.command("study")
def study_cmd(config_path: str) -> None:
    """Run a configured event study."""
    from quant.config import load_config
    from quant.data.universe import list_symbols
    from quant.reporting.report import write_event_study_report
    from quant.research.forward_returns import run_event_study
    from quant.signals.factors import compute_signal

    config = load_config(config_path)
    exclude = set(config.get("exclude_boards") or [])
    # 全期宇宙（at=None 含期内退市股）——单日时点宇宙会引入幸存者偏差
    symbols = config.get("symbols") or list_symbols(
        exclude_boards=exclude or frozenset({"star"}), at=None
    )
    signals = compute_signal(
        str(config["signal"]),
        symbols,
        start=config.get("start"),
        end=config.get("end"),
        signal_params=config.get("signal_params") or None,
    )
    result = run_event_study(
        signals,
        horizons=config.get("horizons", (1, 3, 5, 10, 20)),
        universe=str(config.get("universe", "nostar")),
        start=config.get("start"),
        end=config.get("end"),
        entry=config.get("entry", "next_open"),
        entry_filters=config.get("entry_filters", "ashare"),
    )
    paths = write_event_study_report(
        result,
        config.get("report_dir", "backtest_results"),
        config.get("report_prefix", "study"),
    )
    typer.echo(f"study report: {paths['md']}")


@app.command("research")
def research_cmd(
    config_path: str,
    oos_final: Annotated[
        str | None,
        typer.Option(
            "--oos-final",
            help="Reviewer-only final parameter JSON for the protected holdout path.",
        ),
    ] = None,
    i_am_the_reviewer: Annotated[
        bool,
        typer.Option(
            "--i-am-the-reviewer",
            help="Required for the protected reviewer-only holdout path.",
        ),
    ] = False,
) -> None:
    """Run an IS-only research parameter scan."""
    from quant.config import load_config
    from quant.research.amv_timing import run_amv_research
    from quant.research.exploratory import run_exploratory_research
    from quant.research.optimize import load_research_config, run_param_scan, write_scan_report
    from quant.research.trade_pairs import run_dual_trend_research, run_shortterm_research

    if oos_final is not None:
        if not i_am_the_reviewer:
            typer.echo("protected holdout path requires reviewer confirmation", err=True)
            raise typer.Exit(code=2)
        typer.echo("protected holdout path is reserved for reviewer execution", err=True)
        raise typer.Exit(code=2)

    raw = load_config(config_path)
    if raw.get("kind") == "amv_timing":
        result = run_amv_research(config_path)
        typer.echo(f"research scan: {result.report_paths['md']}")
        return
    if raw.get("kind") == "dual_trend_pairs":
        paths = run_dual_trend_research(config_path)
        typer.echo(f"research scan: {paths['md']}")
        return
    if raw.get("kind") == "shortterm_pairs":
        paths = run_shortterm_research(config_path)
        typer.echo(f"research scan: {paths['md']}")
        return
    if raw.get("kind") == "exploratory_factors":
        paths = run_exploratory_research(config_path)
        typer.echo(f"research scan: {paths['md']}")
        return

    cfg = load_research_config(config_path)
    result = run_param_scan(cfg)
    paths = write_scan_report(result, cfg.report_dir, cfg.name)
    typer.echo(f"research scan: {paths['md']}")


@app.command("ic")
def ic_cmd(
    signal_name: str,
    start: Annotated[str | None, typer.Option(help="Start date, YYYY-MM-DD.")] = None,
    end: Annotated[str | None, typer.Option(help="End date, YYYY-MM-DD.")] = None,
) -> None:
    """Run a RankIC report for a registered signal."""
    from quant.data.universe import list_symbols
    from quant.research.ic import ic_report
    from quant.signals.factors import to_factor

    symbols = list_symbols(exclude_boards={"star"}, at=end)
    factor = to_factor(signal_name, symbols, start, end)
    path = ic_report(signal_name, factor)
    typer.echo(f"ic report: {path}")


@app.command("update")
def update_cmd(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only print planned row counts.")
    ] = False,
) -> None:
    """Preview legacy additions, or publish a fully reconciled atomic snapshot."""
    from quant.config import get_settings
    from quant.etl.update import collect_new_rows
    import pandas as pd

    settings = get_settings()
    if dry_run:
        daily = pd.read_parquet(settings.staging_dir / "daily", columns=["date"])
        last_date = pd.to_datetime(daily["date"]).max()
        new_rows = collect_new_rows(settings.tdx_home, last_date)
        typer.echo(
            f"update dry-run (new-date lower bound; excludes corrections): {len(new_rows)} rows, "
            f"{new_rows['symbol'].nunique() if not new_rows.empty else 0} symbols"
        )
        return
    from quant.etl.restart import update_snapshot
    from quant.platform_cli import output

    output(update_snapshot(settings))


@app.command("validate")
def validate_cmd() -> None:
    """Run the PG-vs-v2 validation report."""
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts" / "validate_vs_pg.py"
    spec = spec_from_file_location("validate_vs_pg", script)
    if spec is None or spec.loader is None:
        raise typer.Exit(code=2)
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    code = module.main()
    if code:
        raise typer.Exit(code=code)
    typer.echo("validate_vs_pg: PASS")


if __name__ == "__main__":
    app()
