from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Annotated

import typer

app = typer.Typer(add_completion=False)
etl_app = typer.Typer(add_completion=False, help="Data platform ETL commands.")
app.add_typer(etl_app, name="etl")

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
    from quant.etl.mirror import extract_zip_baseline, mirror_vipdoc
    from quant.etl.staging import (
        build_blocks_staging,
        build_daily_staging,
        build_flags_staging,
        build_gbbq_staging,
        build_securities_staging,
    )

    settings = get_settings()
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

    for step in expanded:
        if step == "derive":
            raise NotImplementedError(f"etl step '{step}' arrives in a later task card")

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
