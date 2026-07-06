from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Annotated

import typer

app = typer.Typer(add_completion=False)
etl_app = typer.Typer(add_completion=False, help="Data platform ETL commands.")
app.add_typer(etl_app, name="etl")

_ETL_STEPS = ("daily", "gbbq", "securities", "blocks", "derive", "flags")


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
    from quant.etl.staging import build_daily_staging

    settings = get_settings()
    requested = [s.strip() for s in steps.split(",") if s.strip()]
    unknown = [s for s in requested if s not in _ETL_STEPS]
    if unknown:
        typer.echo(f"unknown steps: {unknown}; valid: {_ETL_STEPS}", err=True)
        raise typer.Exit(code=2)

    for step in requested:
        if step != "daily":
            raise NotImplementedError(f"etl step '{step}' arrives in a later task card")

    if "daily" in requested:
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
