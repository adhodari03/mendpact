"""Human-readable and machine-readable scan reports."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from openproof.domain import (
    ConformanceCheckStatus,
    ConformanceReport,
    ScanReport,
    ScanStatus,
)


def write_json_report(report: ScanReport, destination: Path) -> None:
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def write_conformance_report(report: ConformanceReport, destination: Path) -> None:
    destination.write_text(report.model_dump_json(indent=2, by_alias=True), encoding="utf-8")


def render_report(report: ScanReport, console: Console) -> None:
    status_style = {
        ScanStatus.PASSED: "bold green",
        ScanStatus.FAILED: "bold red",
        ScanStatus.ERROR: "bold red",
    }[report.status]
    console.print(f"OpenProof scan: [{status_style}]{report.status.value.upper()}[/]")
    console.print(f"Target: {report.target}")

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
    console.print(f"OpenProof conformance: [{status_style}]{report.status.value.upper()}[/]")
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
