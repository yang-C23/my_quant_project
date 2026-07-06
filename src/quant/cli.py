from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Annotated

import typer

app = typer.Typer(add_completion=False)


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
