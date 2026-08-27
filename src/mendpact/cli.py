"""Command-line interface for MendPact."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Annotated

import anyio
import typer
from rich.console import Console

from mendpact import __version__
from mendpact.conformance import run_server_conformance
from mendpact.domain import ScanStatus, Severity
from mendpact.reporting import (
    render_conformance_report,
    render_report,
    write_conformance_report,
    write_json_report,
)
from mendpact.scanner import scan_mcp_url
from mendpact.security.targets import TargetPolicy

app = typer.Typer(
    name="mendpact",
    help="Protocol-native reliability checks for AI agents.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True),
    ] = None,
) -> None:
    """Run MendPact reliability scans."""


@app.command()
def scan(
    target: Annotated[str, typer.Argument(help="Remote Streamable HTTP MCP endpoint")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the full JSON report to this path"),
    ] = None,
    fail_on: Annotated[
        Severity,
        typer.Option("--fail-on", case_sensitive=False, help="Minimum severity that fails CI"),
    ] = Severity.HIGH,
    allow_private: Annotated[
        bool,
        typer.Option(help="Allow private/loopback targets for deliberate local development"),
    ] = False,
    allow_insecure_http: Annotated[
        bool,
        typer.Option(help="Allow plaintext HTTP for deliberate local development"),
    ] = False,
) -> None:
    """Discover and deterministically inspect a remote MCP endpoint."""

    report = anyio.run(
        partial(
            scan_mcp_url,
            target,
            failure_threshold=fail_on,
            policy=TargetPolicy(
                allow_private=allow_private,
                allow_insecure_http=allow_insecure_http,
            ),
        )
    )
    render_report(report, console)

    if output is not None:
        try:
            write_json_report(report, output)
        except OSError as exc:
            console.print(f"[red]Could not write report:[/] {exc}")
            raise typer.Exit(code=2) from exc
        console.print(f"JSON report: {output}")

    if report.status == ScanStatus.ERROR:
        raise typer.Exit(code=2)
    if report.status == ScanStatus.FAILED:
        raise typer.Exit(code=1)


@app.command()
def conformance(
    target: Annotated[str, typer.Argument(help="Remote Streamable HTTP MCP endpoint")],
    scenario: Annotated[
        str | None,
        typer.Option(help="Run one scenario; defaults to the safe server-initialize scenario"),
    ] = None,
    suite: Annotated[
        str | None,
        typer.Option(help="Run an upstream suite: active, all, or pending"),
    ] = None,
    spec_version: Annotated[
        str | None,
        typer.Option("--spec-version", help="MCP specification version passed to the runner"),
    ] = None,
    expected_failures: Annotated[
        Path | None,
        typer.Option(
            "--expected-failures",
            help="Upstream YAML baseline containing expected conformance failures",
        ),
    ] = None,
    allow_tool_calls: Annotated[
        bool,
        typer.Option(help="Authorize scenarios that may invoke tools on an isolated test server"),
    ] = False,
    allow_private: Annotated[
        bool,
        typer.Option(help="Allow private/loopback targets for deliberate local development"),
    ] = False,
    allow_insecure_http: Annotated[
        bool,
        typer.Option(help="Allow plaintext HTTP for deliberate local development"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(help="Request verbose output from the official runner"),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the normalized JSON report to this path"),
    ] = None,
) -> None:
    """Run the pinned official MCP server conformance framework."""

    report = anyio.run(
        partial(
            run_server_conformance,
            target,
            scenario=scenario,
            suite=suite,
            spec_version=spec_version,
            expected_failures=expected_failures,
            verbose=verbose,
            allow_tool_calls=allow_tool_calls,
            policy=TargetPolicy(
                allow_private=allow_private,
                allow_insecure_http=allow_insecure_http,
            ),
        )
    )
    render_conformance_report(report, console)

    if output is not None:
        try:
            write_conformance_report(report, output)
        except OSError as exc:
            console.print(f"[red]Could not write report:[/] {exc}")
            raise typer.Exit(code=2) from exc
        console.print(f"JSON report: {output}")

    if report.status == ScanStatus.ERROR:
        raise typer.Exit(code=2)
    if report.status == ScanStatus.FAILED:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
