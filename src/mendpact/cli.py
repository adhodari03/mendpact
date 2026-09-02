"""Command-line interface for MendPact."""

from __future__ import annotations

from enum import StrEnum
from functools import partial
from pathlib import Path
from shlex import quote
from typing import Annotated

import anyio
import typer
from rich.console import Console

from mendpact import __version__
from mendpact.authorization import audit_oauth_metadata
from mendpact.baseline import (
    BaselineLifecycleError,
    inspect_scan_baseline,
    promote_scan_baseline,
)
from mendpact.behavior import (
    evaluate_mcp_url,
    load_behavior_suite,
    load_replay_plan,
    replay_plan_from_report,
)
from mendpact.conformance import run_server_conformance
from mendpact.contract_diff import diff_scan_reports, load_scan_report
from mendpact.domain import (
    BehaviorThresholds,
    ContractImpact,
    ModelComparisonThresholds,
    PolicySnapshot,
    ScanStatus,
    Severity,
)
from mendpact.drivers.base import ModelDriver
from mendpact.drivers.openai import (
    OpenAIDriverConfigurationError,
    OpenAIResponsesDriver,
)
from mendpact.drivers.replay import ReplayDriver
from mendpact.guard import guard_mcp_url
from mendpact.model_comparison import compare_behavior_reports, load_behavior_report
from mendpact.policy import PolicyConfigurationError, load_policy, target_policy
from mendpact.project_init import ProjectInitializationError, initialize_project
from mendpact.regression import (
    baseline_from_report,
    compare_to_baseline,
    load_behavior_baseline,
)
from mendpact.reporting import (
    render_authorization_report,
    render_baseline_inspection,
    render_behavior_report,
    render_conformance_report,
    render_contract_diff_report,
    render_guard_report,
    render_model_comparison_report,
    render_report,
    write_authorization_report,
    write_behavior_baseline,
    write_behavior_report,
    write_conformance_report,
    write_contract_diff_report,
    write_guard_report,
    write_json_report,
    write_model_comparison_report,
    write_replay_plan,
)
from mendpact.scanner import scan_mcp_url
from mendpact.security.auth import (
    AuthenticationConfigurationError,
    BearerAuthentication,
    load_bearer_authentication,
)
from mendpact.security.targets import TargetPolicy

app = typer.Typer(
    name="mendpact",
    help="Protocol-native reliability checks for AI agents.",
    no_args_is_help=True,
)
console = Console()
baseline_app = typer.Typer(
    help="Inspect and deliberately promote MCP contract baselines.",
    no_args_is_help=True,
)
app.add_typer(baseline_app, name="baseline")


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


def _reject_policy_overrides(ctx: typer.Context, option_names: tuple[str, ...]) -> None:
    explicit = [
        f"--{name.replace('_', '-')}"
        for name in option_names
        if (
            (source := ctx.get_parameter_source(name)) is not None
            and source.name == "COMMANDLINE"
        )
    ]
    if explicit:
        raise ValueError(
            "--policy cannot be combined with policy-controlled options: "
            + ", ".join(explicit)
        )


def _target_authentication(
    policy: PolicySnapshot | None,
    auth_token_env: str | None,
) -> BearerAuthentication | None:
    environment_variable = policy.bearer_token_env if policy else auth_token_env
    return load_bearer_authentication(environment_variable)


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True),
    ] = None,
) -> None:
    """Run MendPact reliability scans."""


@app.command("init")
def initialize(
    target: Annotated[
        str,
        typer.Option(
            "--target",
            help="Production HTTPS Streamable HTTP MCP endpoint written to the workflow",
        ),
    ],
    directory: Annotated[
        Path,
        typer.Argument(help="Repository directory to initialize"),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option(help="Replace only MendPact files generated by this command"),
    ] = False,
) -> None:
    """Create a production-safe MendPact policy and GitHub workflow."""

    try:
        generated = initialize_project(directory, target=target, force=force)
    except (OSError, ProjectInitializationError) as exc:
        console.print(f"[red]Could not initialize MendPact:[/] {exc}")
        raise typer.Exit(code=2) from exc

    root = directory.expanduser().absolute()
    console.print("[green]MendPact project initialized.[/]")
    for path in generated:
        console.print(f"  {path.relative_to(root)}")
    console.print("Review the example scenario before using guard mode.")
    typer.echo("Capture the first baseline candidate with:")
    typer.echo(f"  cd {quote(str(root))}")
    typer.echo(
        f"  mendpact scan {quote(target)} --policy mendpact.toml "
        "--output mendpact/candidates/candidate-scan.json"
    )
    typer.echo("Then inspect and deliberately promote that exact scan:")
    typer.echo("  mendpact baseline inspect mendpact/candidates/candidate-scan.json")
    typer.echo(
        "  mendpact baseline promote mendpact/candidates/candidate-scan.json "
        "mendpact/baselines/baseline-scan.json "
        f"--accept-scan-id \"paste-scan-id-here\" --expected-target {quote(target)}"
    )


@app.command()
def scan(
    ctx: typer.Context,
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
    policy_file: Annotated[
        Path | None,
        typer.Option(
            "--policy",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Versioned TOML policy that owns thresholds and target allowances",
        ),
    ] = None,
    auth_token_env: Annotated[
        str | None,
        typer.Option(
            "--auth-token-env",
            help="Environment variable containing a bearer token; never pass the token itself",
        ),
    ] = None,
) -> None:
    """Discover and deterministically inspect a remote MCP endpoint."""

    try:
        applied_policy = load_policy(policy_file) if policy_file is not None else None
        if applied_policy is not None:
            _reject_policy_overrides(
                ctx,
                (
                    "fail_on",
                    "allow_private",
                    "allow_insecure_http",
                    "auth_token_env",
                ),
            )
        authentication = _target_authentication(applied_policy, auth_token_env)
    except (
        AuthenticationConfigurationError,
        PolicyConfigurationError,
        ValueError,
    ) as exc:
        console.print(f"[red]Could not configure scan policy:[/] {exc}")
        raise typer.Exit(code=2) from exc

    failure_threshold = applied_policy.scan_fail_on if applied_policy else fail_on
    network_policy = (
        target_policy(applied_policy)
        if applied_policy
        else TargetPolicy(
            allow_private=allow_private,
            allow_insecure_http=allow_insecure_http,
        )
    )

    report = anyio.run(
        partial(
            scan_mcp_url,
            target,
            failure_threshold=failure_threshold,
            policy=network_policy,
            applied_policy=applied_policy,
            authentication=authentication,
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


@app.command("auth-check")
def authorization_check(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Remote Streamable HTTP MCP endpoint")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the authorization audit JSON report"),
    ] = None,
    fail_on: Annotated[
        Severity,
        typer.Option(
            "--fail-on",
            case_sensitive=False,
            help="Minimum authorization finding severity that fails CI",
        ),
    ] = Severity.HIGH,
    allow_private: Annotated[
        bool,
        typer.Option(help="Allow private targets for deliberate local development"),
    ] = False,
    allow_insecure_http: Annotated[
        bool,
        typer.Option(help="Allow plaintext target probing for deliberate local development"),
    ] = False,
    policy_file: Annotated[
        Path | None,
        typer.Option(
            "--policy",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Versioned TOML policy that owns thresholds and target allowances",
        ),
    ] = None,
) -> None:
    """Audit OAuth discovery metadata without loading or transmitting a token."""

    try:
        applied_policy = load_policy(policy_file) if policy_file is not None else None
        if applied_policy is not None:
            _reject_policy_overrides(
                ctx,
                ("fail_on", "allow_private", "allow_insecure_http"),
            )
    except (PolicyConfigurationError, ValueError) as exc:
        console.print(f"[red]Could not configure authorization audit:[/] {exc}")
        raise typer.Exit(code=2) from exc

    failure_threshold = applied_policy.scan_fail_on if applied_policy else fail_on
    network_policy = (
        target_policy(applied_policy)
        if applied_policy
        else TargetPolicy(
            allow_private=allow_private,
            allow_insecure_http=allow_insecure_http,
        )
    )
    report = anyio.run(
        partial(
            audit_oauth_metadata,
            target,
            failure_threshold=failure_threshold,
            policy=network_policy,
            applied_policy=applied_policy,
        )
    )
    render_authorization_report(report, console)
    if output is not None:
        try:
            write_authorization_report(report, output)
        except OSError as exc:
            console.print(f"[red]Could not write authorization report:[/] {exc}")
            raise typer.Exit(code=2) from exc
        console.print(f"JSON report: {output}")

    if report.status == ScanStatus.ERROR:
        raise typer.Exit(code=2)
    if report.status == ScanStatus.FAILED:
        raise typer.Exit(code=1)


@baseline_app.command("inspect")
def inspect_contract_baseline(
    artifact: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="MendPact scan artifact to validate for baseline use",
        ),
    ],
) -> None:
    """Validate and identify a contract baseline without contacting its target."""

    try:
        inspection = inspect_scan_baseline(artifact)
    except BaselineLifecycleError as exc:
        console.print(f"[red]Invalid contract baseline:[/] {exc}")
        raise typer.Exit(code=2) from exc

    render_baseline_inspection(inspection, console)
    if inspection.requires_failed_scan_acceptance:
        raise typer.Exit(code=1)


@baseline_app.command("promote")
def promote_contract_baseline(
    candidate: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="Reviewed candidate scan artifact",
        ),
    ],
    destination: Annotated[
        Path,
        typer.Argument(help="Versioned contract baseline destination"),
    ],
    accept_scan_id: Annotated[
        str,
        typer.Option(
            "--accept-scan-id",
            help="Exact candidate scan ID being approved",
        ),
    ],
    expected_target: Annotated[
        str | None,
        typer.Option(help="Require an exact candidate target match"),
    ] = None,
    accept_failed_scan: Annotated[
        bool,
        typer.Option(
            help="Explicitly approve a complete scan that failed its policy threshold"
        ),
    ] = False,
    replace: Annotated[
        bool,
        typer.Option(help="Replace an existing baseline after review"),
    ] = False,
) -> None:
    """Promote one exactly acknowledged scan to a committed contract baseline."""

    try:
        inspection = promote_scan_baseline(
            candidate,
            destination,
            accepted_scan_id=accept_scan_id,
            expected_target=expected_target,
            accept_failed_scan=accept_failed_scan,
            replace=replace,
        )
    except BaselineLifecycleError as exc:
        console.print(f"[red]Could not promote contract baseline:[/] {exc}")
        raise typer.Exit(code=2) from exc

    render_baseline_inspection(inspection, console)
    console.print(f"[green]Promoted baseline:[/] {destination}")


@app.command("diff")
def contract_diff(
    baseline: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="Baseline MendPact scan report",
        ),
    ],
    candidate: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="Candidate MendPact scan report",
        ),
    ],
    scenario: Annotated[
        Path | None,
        typer.Option(
            "--scenario",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Optional behavior suite used to calculate blast radius",
        ),
    ] = None,
    fail_on: Annotated[
        ContractImpact,
        typer.Option(
            "--fail-on",
            case_sensitive=False,
            help="Minimum compatibility impact that fails CI",
        ),
    ] = ContractImpact.BREAKING,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the contract diff JSON report"),
    ] = None,
) -> None:
    """Compare two scan artifacts and report MCP contract changes."""

    try:
        baseline_report = load_scan_report(baseline)
        candidate_report = load_scan_report(candidate)
        behavior_suite = load_behavior_suite(scenario) if scenario is not None else None
        report = diff_scan_reports(
            baseline_report,
            candidate_report,
            suite=behavior_suite,
            failure_threshold=fail_on,
        )
    except (OSError, ValueError) as exc:
        console.print(f"[red]Could not compare MCP contracts:[/] {exc}")
        raise typer.Exit(code=2) from exc

    render_contract_diff_report(report, console)
    if output is not None:
        try:
            write_contract_diff_report(report, output)
        except OSError as exc:
            console.print(f"[red]Could not write contract diff report:[/] {exc}")
            raise typer.Exit(code=2) from exc
        console.print(f"JSON report: {output}")

    if report.status == ScanStatus.FAILED:
        raise typer.Exit(code=1)


@app.command()
def guard(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Remote Streamable HTTP MCP endpoint")],
    baseline: Annotated[
        Path,
        typer.Option(
            "--baseline",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Committed MendPact scan used as the contract baseline",
        ),
    ],
    scenario: Annotated[
        Path | None,
        typer.Option(
            "--scenario",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Behavior suite used to calculate and replay the blast radius",
        ),
    ] = None,
    replay: Annotated[
        Path | None,
        typer.Option(
            "--replay",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Recorded decisions for affected behavior scenarios",
        ),
    ] = None,
    repetitions: Annotated[
        int,
        typer.Option(min=1, max=100, help="Replay decisions per affected scenario"),
    ] = 1,
    scan_fail_on: Annotated[
        Severity,
        typer.Option(
            "--scan-fail-on",
            case_sensitive=False,
            help="Minimum deterministic finding severity that fails CI",
        ),
    ] = Severity.HIGH,
    contract_fail_on: Annotated[
        ContractImpact,
        typer.Option(
            "--contract-fail-on",
            case_sensitive=False,
            help="Minimum contract-change impact that fails CI",
        ),
    ] = ContractImpact.BREAKING,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the unified guard JSON report"),
    ] = None,
    save_scan: Annotated[
        Path | None,
        typer.Option(help="Save the newly discovered scan as a candidate artifact"),
    ] = None,
    allow_private: Annotated[
        bool,
        typer.Option(help="Allow private/loopback targets for deliberate local development"),
    ] = False,
    allow_insecure_http: Annotated[
        bool,
        typer.Option(help="Allow plaintext HTTP for deliberate local development"),
    ] = False,
    policy_file: Annotated[
        Path | None,
        typer.Option(
            "--policy",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Versioned TOML policy that owns thresholds and target allowances",
        ),
    ] = None,
    auth_token_env: Annotated[
        str | None,
        typer.Option(
            "--auth-token-env",
            help="Environment variable containing a bearer token; never pass the token itself",
        ),
    ] = None,
) -> None:
    """Run scan, contract diff, and affected deterministic replays in one CI command."""

    try:
        applied_policy = load_policy(policy_file) if policy_file is not None else None
        if applied_policy is not None:
            _reject_policy_overrides(
                ctx,
                (
                    "scan_fail_on",
                    "contract_fail_on",
                    "allow_private",
                    "allow_insecure_http",
                    "auth_token_env",
                ),
            )
        authentication = _target_authentication(applied_policy, auth_token_env)
        if (scenario is None) != (replay is None):
            raise ValueError("--scenario and --replay must be supplied together.")
        input_paths = {
            path.resolve()
            for path in (baseline, scenario, replay)
            if path is not None
        }
        destinations = [
            ("--output", output.resolve()) if output is not None else None,
            ("--save-scan", save_scan.resolve()) if save_scan is not None else None,
        ]
        resolved_destinations = [item for item in destinations if item is not None]
        for option, destination in resolved_destinations:
            if destination in input_paths:
                raise ValueError(f"{option} cannot overwrite a guard input file.")
        if len({path for _, path in resolved_destinations}) != len(
            resolved_destinations
        ):
            raise ValueError("--output and --save-scan must use different paths.")
        baseline_report = load_scan_report(baseline)
        behavior_suite = load_behavior_suite(scenario) if scenario is not None else None
        replay_plan = load_replay_plan(replay) if replay is not None else None
    except (
        AuthenticationConfigurationError,
        OSError,
        PolicyConfigurationError,
        ValueError,
    ) as exc:
        console.print(f"[red]Could not configure guard:[/] {exc}")
        raise typer.Exit(code=2) from exc

    effective_scan_fail_on = applied_policy.scan_fail_on if applied_policy else scan_fail_on
    effective_contract_fail_on = (
        applied_policy.contract_fail_on if applied_policy else contract_fail_on
    )
    network_policy = (
        target_policy(applied_policy)
        if applied_policy
        else TargetPolicy(
            allow_private=allow_private,
            allow_insecure_http=allow_insecure_http,
        )
    )

    report = anyio.run(
        partial(
            guard_mcp_url,
            target,
            baseline_report,
            suite=behavior_suite,
            replay=replay_plan,
            repetitions=repetitions,
            scan_failure_threshold=effective_scan_fail_on,
            contract_failure_threshold=effective_contract_fail_on,
            policy=network_policy,
            applied_policy=applied_policy,
            authentication=authentication,
        )
    )
    render_guard_report(report, console)

    try:
        if output is not None:
            write_guard_report(report, output)
            console.print(f"JSON report: {output}")
        if save_scan is not None:
            write_json_report(report.scan, save_scan)
            console.print(f"Candidate scan: {save_scan}")
    except OSError as exc:
        console.print(f"[red]Could not write guard artifacts:[/] {exc}")
        raise typer.Exit(code=2) from exc

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
    auth_token_env: Annotated[
        str | None,
        typer.Option(
            "--auth-token-env",
            help="Environment variable containing a bearer token; never pass the token itself",
        ),
    ] = None,
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
        authentication = load_bearer_authentication(auth_token_env)
    except (
        AuthenticationConfigurationError,
        OSError,
        ValueError,
        OpenAIDriverConfigurationError,
    ) as exc:
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
            authentication=authentication,
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


@app.command("compare-models")
def compare_models(
    reference: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="Reference MendPact behavior report",
        ),
    ],
    candidates: Annotated[
        list[Path],
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="One or more candidate MendPact behavior reports",
        ),
    ],
    max_overall_pass_rate_drop: Annotated[
        float,
        typer.Option(
            min=0.0,
            max=1.0,
            help="Maximum candidate pass-rate drop from the reference",
        ),
    ] = 0.0,
    max_scenario_pass_rate_drop: Annotated[
        float,
        typer.Option(
            min=0.0,
            max=1.0,
            help="Maximum pass-rate drop allowed for any one scenario",
        ),
    ] = 0.0,
    allow_new_confusions: Annotated[
        bool,
        typer.Option(
            help="Report newly confused tool pairs as warnings instead of failures",
        ),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the model comparison JSON report"),
    ] = None,
) -> None:
    """Compare complete behavior reports without making provider API calls."""

    try:
        input_paths = {reference.resolve(), *(path.resolve() for path in candidates)}
        if output is not None and output.resolve() in input_paths:
            raise ValueError("--output cannot overwrite an input behavior report.")
        report = compare_behavior_reports(
            load_behavior_report(reference),
            [load_behavior_report(path) for path in candidates],
            ModelComparisonThresholds(
                max_overall_pass_rate_drop=max_overall_pass_rate_drop,
                max_scenario_pass_rate_drop=max_scenario_pass_rate_drop,
                allow_new_confusions=allow_new_confusions,
            ),
        )
    except (OSError, ValueError) as exc:
        console.print(f"[red]Could not compare model behavior:[/] {exc}")
        raise typer.Exit(code=2) from exc

    render_model_comparison_report(report, console)
    if output is not None:
        try:
            write_model_comparison_report(report, output)
        except OSError as exc:
            console.print(f"[red]Could not write model comparison report:[/] {exc}")
            raise typer.Exit(code=2) from exc
        console.print(f"JSON report: {output}")

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
