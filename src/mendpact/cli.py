"""Command-line interface for MendPact."""

from __future__ import annotations

from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Annotated

import anyio
import typer
from rich.console import Console

from mendpact import __version__
from mendpact.behavior import (
    evaluate_mcp_url,
    load_behavior_suite,
    load_replay_plan,
    replay_plan_from_report,
)
from mendpact.conformance import run_server_conformance
from mendpact.domain import BehaviorThresholds, ScanStatus, Severity
from mendpact.drivers.base import ModelDriver
from mendpact.drivers.openai import (
    OpenAIDriverConfigurationError,
    OpenAIResponsesDriver,
)
from mendpact.drivers.replay import ReplayDriver
from mendpact.regression import (
    baseline_from_report,
    compare_to_baseline,
    load_behavior_baseline,
)
from mendpact.reporting import (
    render_behavior_report,
    render_conformance_report,
    render_report,
    write_behavior_baseline,
    write_behavior_report,
    write_conformance_report,
    write_json_report,
    write_replay_plan,
)
from mendpact.scanner import scan_mcp_url
from mendpact.security.targets import TargetPolicy

app = typer.Typer(
    name="mendpact",
    help="Protocol-native reliability checks for AI agents.",
    no_args_is_help=True,
)
console = Console()


class BehaviorDriver(StrEnum):
    REPLAY = "replay"
    OPENAI = "openai"


def _build_behavior_driver(
    driver: BehaviorDriver,
    *,
    replay: Path | None,
    model: str | None,
) -> ModelDriver:
    if driver == BehaviorDriver.REPLAY:
        if replay is None:
            raise ValueError("--replay is required when --driver is replay.")
        if model is not None:
            raise ValueError("--model can only be used with --driver openai.")
        return ReplayDriver(load_replay_plan(replay))

    if replay is not None:
        raise ValueError("--replay can only be used with --driver replay.")
    if model is None:
        raise ValueError("--model is required when --driver is openai.")
    return OpenAIResponsesDriver(model=model)


def _behavior_thresholds(
    base: BehaviorThresholds,
    *,
    min_pass_rate: float | None,
    max_pass_rate_drop: float | None,
    max_failed_trials: int | None,
) -> BehaviorThresholds:
    updates: dict[str, float | int] = {}
    if min_pass_rate is not None:
        updates["min_pass_rate"] = min_pass_rate
    if max_pass_rate_drop is not None:
        updates["max_pass_rate_drop"] = max_pass_rate_drop
    if max_failed_trials is not None:
        updates["max_failed_trials"] = max_failed_trials
    return base.model_copy(update=updates)


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
def evaluate(
    target: Annotated[str, typer.Argument(help="Remote Streamable HTTP MCP endpoint")],
    scenario: Annotated[
        Path,
        typer.Option(
            "--scenario",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Versioned JSON behavior suite",
        ),
    ],
    replay: Annotated[
        Path | None,
        typer.Option(
            "--replay",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Recorded JSON tool decisions to replay",
        ),
    ] = None,
    driver: Annotated[
        BehaviorDriver,
        typer.Option(
            "--driver",
            case_sensitive=False,
            help="Model decision driver",
        ),
    ] = BehaviorDriver.REPLAY,
    model: Annotated[
        str | None,
        typer.Option(help="OpenAI model name used for live evaluations"),
    ] = None,
    repetitions: Annotated[
        int,
        typer.Option(min=1, max=100, help="Number of decisions per scenario"),
    ] = 1,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the full JSON report to this path"),
    ] = None,
    save_replay: Annotated[
        Path | None,
        typer.Option(
            "--save-replay",
            help="Save complete model decisions as deterministic replay input",
        ),
    ] = None,
    baseline: Annotated[
        Path | None,
        typer.Option(
            "--baseline",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Compare this run with a versioned behavior baseline",
        ),
    ] = None,
    save_baseline: Annotated[
        Path | None,
        typer.Option(
            "--save-baseline",
            help="Save this complete run as a versioned behavior baseline",
        ),
    ] = None,
    min_pass_rate: Annotated[
        float | None,
        typer.Option(min=0.0, max=1.0, help="Minimum acceptable current pass rate"),
    ] = None,
    max_pass_rate_drop: Annotated[
        float | None,
        typer.Option(min=0.0, max=1.0, help="Maximum pass-rate drop from the baseline"),
    ] = None,
    max_failed_trials: Annotated[
        int | None,
        typer.Option(min=0, help="Maximum acceptable failed trials"),
    ] = None,
    allow_private: Annotated[
        bool,
        typer.Option(help="Allow private/loopback targets for deliberate local development"),
    ] = False,
    allow_insecure_http: Annotated[
        bool,
        typer.Option(help="Allow plaintext HTTP for deliberate local development"),
    ] = False,
) -> None:
    """Grade replayed or live model tool decisions against an MCP endpoint."""

    try:
        behavior_suite = load_behavior_suite(scenario)
        model_driver = _build_behavior_driver(driver, replay=replay, model=model)
        saved_baseline = load_behavior_baseline(baseline) if baseline is not None else None
        if (
            saved_baseline is None
            and save_baseline is None
            and any(
                value is not None
                for value in (min_pass_rate, max_pass_rate_drop, max_failed_trials)
            )
        ):
            raise ValueError(
                "Behavior thresholds require --baseline or --save-baseline."
            )
        thresholds = _behavior_thresholds(
            saved_baseline.thresholds if saved_baseline else BehaviorThresholds(),
            min_pass_rate=min_pass_rate,
            max_pass_rate_drop=max_pass_rate_drop,
            max_failed_trials=max_failed_trials,
        )
    except (OSError, ValueError, OpenAIDriverConfigurationError) as exc:
        console.print(f"[red]Could not configure behavior evaluation:[/] {exc}")
        raise typer.Exit(code=2) from exc

    report = anyio.run(
        partial(
            evaluate_mcp_url,
            target,
            behavior_suite,
            model_driver,
            repetitions=repetitions,
            policy=TargetPolicy(
                allow_private=allow_private,
                allow_insecure_http=allow_insecure_http,
            ),
        )
    )

    if saved_baseline is not None and report.status != ScanStatus.ERROR:
        try:
            report = compare_to_baseline(report, saved_baseline, thresholds)
        except ValueError as exc:
            console.print(f"[red]Could not compare behavior baseline:[/] {exc}")
            raise typer.Exit(code=2) from exc
    render_behavior_report(report, console)

    if output is not None:
        try:
            write_behavior_report(report, output)
        except OSError as exc:
            console.print(f"[red]Could not write report:[/] {exc}")
            raise typer.Exit(code=2) from exc
        console.print(f"JSON report: {output}")

    if save_replay is not None:
        try:
            write_replay_plan(replay_plan_from_report(report), save_replay)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Could not write replay data:[/] {exc}")
            raise typer.Exit(code=2) from exc
        console.print(f"Replay data: {save_replay}")

    if save_baseline is not None:
        try:
            write_behavior_baseline(
                baseline_from_report(report, thresholds),
                save_baseline,
            )
        except (OSError, ValueError) as exc:
            console.print(f"[red]Could not write behavior baseline:[/] {exc}")
            raise typer.Exit(code=2) from exc
        console.print(f"Behavior baseline: {save_baseline}")

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
