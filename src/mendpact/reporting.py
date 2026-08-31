"""Human-readable and machine-readable scan reports."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mendpact.domain import (
    BehaviorBaseline,
    BehaviorReport,
    ConformanceCheckStatus,
    ConformanceReport,
    ContractDiffReport,
    ContractImpact,
    GuardReport,
    RegressionImpact,
    ReplayPlan,
    ScanReport,
    ScanStatus,
)


def write_json_report(report: ScanReport, destination: Path) -> None:
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def write_conformance_report(report: ConformanceReport, destination: Path) -> None:
    destination.write_text(report.model_dump_json(indent=2, by_alias=True), encoding="utf-8")


def write_behavior_report(report: BehaviorReport, destination: Path) -> None:
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def write_contract_diff_report(report: ContractDiffReport, destination: Path) -> None:
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def write_guard_report(report: GuardReport, destination: Path) -> None:
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def write_behavior_baseline(baseline: BehaviorBaseline, destination: Path) -> None:
    destination.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")


def write_replay_plan(plan: ReplayPlan, destination: Path) -> None:
    destination.write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def render_report(report: ScanReport, console: Console) -> None:
    status_style = {
        ScanStatus.PASSED: "bold green",
        ScanStatus.FAILED: "bold red",
        ScanStatus.ERROR: "bold red",
    }[report.status]
    console.print(f"MendPact scan: [{status_style}]{report.status.value.upper()}[/]")
    console.print(f"Target: {report.target}")
    if report.policy:
        console.print(
            f"Policy: {report.policy.name} ({report.policy.profile.value}) | "
            f"Scan: {report.policy.scan_fail_on.value} | "
            f"Contract: {report.policy.contract_fail_on.value}"
        )

    if report.errors:
        for error in report.errors:
            console.print(f"[red]Error:[/] {error}")
        return

    if report.summary and report.graph:
        console.print(
            f"Protocol: MCP {report.graph.protocol_version or 'unknown'} | "
            f"Tools: {report.summary.tool_count} | "
            f"Resources: {report.summary.resource_count} | "
            f"Prompts: {report.summary.prompt_count}"
        )

    if not report.findings:
        console.print("[green]No deterministic findings.[/]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Severity", width=10)
    table.add_column("Rule", width=12)
    table.add_column("Subject", overflow="fold")
    table.add_column("Finding", overflow="fold")
    for finding in report.findings:
        table.add_row(
            finding.severity.value.upper(),
            finding.rule_id,
            finding.subject or "-",
            f"{finding.title}: {finding.message}",
        )
    console.print(table)


def render_conformance_report(report: ConformanceReport, console: Console) -> None:
    status_style = {
        ScanStatus.PASSED: "bold green",
        ScanStatus.FAILED: "bold red",
        ScanStatus.ERROR: "bold red",
    }[report.status]
    console.print(f"MendPact conformance: [{status_style}]{report.status.value.upper()}[/]")
    console.print(f"Target: {report.target}")
    console.print(f"Runner: {report.runner_package}@{report.runner_version}")

    if report.errors:
        for error in report.errors:
            console.print(f"[red]Error:[/] {error}")

    if report.summary:
        counts = report.summary.checks_by_status
        console.print(
            f"Scenarios: {report.summary.scenario_count} | "
            f"Checks: {report.summary.check_count} | "
            f"Passed: {counts[ConformanceCheckStatus.SUCCESS.value]} | "
            f"Failed: {counts[ConformanceCheckStatus.FAILURE.value]} | "
            f"Skipped: {counts[ConformanceCheckStatus.SKIPPED.value]}"
        )

    failed_checks = [
        (scenario.name, check)
        for scenario in report.scenarios
        for check in scenario.checks
        if check.status == ConformanceCheckStatus.FAILURE
    ]
    if not failed_checks:
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Scenario", overflow="fold")
    table.add_column("Check", overflow="fold")
    table.add_column("Failure", overflow="fold")
    for scenario_name, check in failed_checks:
        table.add_row(
            scenario_name,
            check.id,
            check.error_message or check.description,
        )
    console.print(table)


def render_contract_diff_report(report: ContractDiffReport, console: Console) -> None:
    status_style = {
        ScanStatus.PASSED: "bold green",
        ScanStatus.FAILED: "bold red",
        ScanStatus.ERROR: "bold red",
    }[report.status]
    console.print(f"MendPact contract diff: [{status_style}]{report.status.value.upper()}[/]")
    console.print(f"Baseline: {report.baseline_target}")
    console.print(f"Candidate: {report.candidate_target}")
    counts = report.summary.changes_by_impact
    console.print(
        f"Changes: {report.summary.change_count} | "
        f"Breaking: {counts[ContractImpact.BREAKING.value]} | "
        f"Risky: {counts[ContractImpact.RISKY.value]} | "
        f"Compatible: {counts[ContractImpact.COMPATIBLE.value]} | "
        f"Affected scenarios: {report.summary.affected_scenario_count}"
    )

    if not report.changes:
        console.print("[green]No contract changes.[/]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Impact", width=11)
    table.add_column("Rule", width=12)
    table.add_column("Subject", overflow="fold")
    table.add_column("Change", overflow="fold")
    table.add_column("Scenarios", overflow="fold")
    styles = {
        ContractImpact.BREAKING: "red",
        ContractImpact.RISKY: "yellow",
        ContractImpact.COMPATIBLE: "green",
    }
    for change in report.changes:
        table.add_row(
            f"[{styles[change.impact]}]{change.impact.value.upper()}[/]",
            change.rule_id,
            change.subject,
            change.message,
            ", ".join(change.affected_scenarios) or "-",
        )
    console.print(table)


def render_guard_report(report: GuardReport, console: Console) -> None:
    status_style = {
        ScanStatus.PASSED: "bold green",
        ScanStatus.FAILED: "bold red",
        ScanStatus.ERROR: "bold red",
    }[report.status]
    summary = report.summary
    console.print(f"MendPact guard: [{status_style}]{report.status.value.upper()}[/]")
    console.print(f"Target: {report.target}")
    if report.policy:
        console.print(
            f"Policy: {report.policy.name} ({report.policy.profile.value}) | "
            f"Scan: {report.policy.scan_fail_on.value} | "
            f"Contract: {report.policy.contract_fail_on.value}"
        )
    console.print(
        f"Scan: {summary.scan_status.value} | "
        f"Contract: {summary.contract_status.value if summary.contract_status else 'skipped'} | "
        f"Behavior: {summary.behavior_status.value if summary.behavior_status else 'skipped'}"
    )
    console.print(
        f"Affected scenarios: {summary.affected_scenario_count} | "
        f"Evaluated scenarios: {summary.evaluated_scenario_count}"
    )
    if report.behavior_skipped_reason:
        console.print(f"Behavior replay: {report.behavior_skipped_reason}")
    for error in report.errors:
        console.print(f"[red]Error:[/] {error}")


def render_behavior_report(report: BehaviorReport, console: Console) -> None:
    status_style = {
        ScanStatus.PASSED: "bold green",
        ScanStatus.FAILED: "bold red",
        ScanStatus.ERROR: "bold red",
    }[report.status]
    console.print(f"MendPact behavior: [{status_style}]{report.status.value.upper()}[/]")
    console.print(f"Target: {report.target}")
    console.print(
        f"Suite: {report.suite_name} | Driver: {report.driver} | "
        f"Model: {report.model} | Repetitions: {report.repetitions}"
    )

    if report.errors:
        for error in report.errors:
            console.print(f"[red]Error:[/] {error}")

    if report.summary:
        console.print(
            f"Scenarios: {report.summary.scenario_count} | "
            f"Trials: {report.summary.trial_count} | "
            f"Passed: {report.summary.passed_trials} | "
            f"Failed: {report.summary.failed_trials} | "
            f"Pass rate: {report.summary.pass_rate:.1%}"
        )
        if report.summary.total_tokens or report.summary.total_latency_ms:
            console.print(
                f"Provider usage: {report.summary.total_tokens} tokens "
                f"({report.summary.input_tokens} input, "
                f"{report.summary.output_tokens} output) | "
                f"Latency: {report.summary.total_latency_ms:.0f} ms"
            )

    if report.regression:
        regression = report.regression
        statistics = ""
        if regression.one_sided_p_value is not None:
            statistics = f" | One-sided p: {regression.one_sided_p_value:.3f}"
        console.print(
            f"Baseline: {regression.baseline_pass_rate:.1%} | "
            f"Current: {regression.current_pass_rate:.1%} | "
            f"Drop: {regression.pass_rate_drop:.1%}{statistics}"
        )
        if regression.findings:
            regression_table = Table(show_header=True, header_style="bold")
            regression_table.add_column("Impact", width=9)
            regression_table.add_column("Rule", width=12)
            regression_table.add_column("Baseline difference", overflow="fold")
            for finding in regression.findings:
                style = "red" if finding.impact == RegressionImpact.FAILURE else "yellow"
                regression_table.add_row(
                    f"[{style}]{finding.impact.value.upper()}[/]",
                    finding.rule_id,
                    finding.message,
                )
            console.print(regression_table)

    failed_trials = [trial for trial in report.trials if not trial.grade.passed]
    if not failed_trials:
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Scenario", overflow="fold")
    table.add_column("Attempt", justify="right")
    table.add_column("Expected", overflow="fold")
    table.add_column("Selected", overflow="fold")
    table.add_column("Reason", overflow="fold")
    for trial in failed_trials:
        table.add_row(
            trial.scenario.id,
            str(trial.trace.attempt),
            trial.scenario.expectation.tool,
            trial.trace.selected_tool or "-",
            " ".join(trial.grade.reasons),
        )
    console.print(table)
