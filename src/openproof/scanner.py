"""Scan orchestration independent of the CLI and future hosted API."""

from __future__ import annotations

from typing import Any

from openproof.adapters.mcp import discover_mcp_target
from openproof.checks.rules import run_deterministic_checks
from openproof.domain import ScanReport, ScanStatus, Severity, summarize
from openproof.security.targets import TargetPolicy, validate_target_url


async def scan_mcp_url(
    target: str,
    *,
    failure_threshold: Severity = Severity.HIGH,
    policy: TargetPolicy | None = None,
) -> ScanReport:
    policy = policy or TargetPolicy()
    try:
        await validate_target_url(target, policy)
        graph = await discover_mcp_target(target)
    except Exception as exc:
        return ScanReport(
            target=target,
            status=ScanStatus.ERROR,
            failure_threshold=failure_threshold,
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    findings = run_deterministic_checks(graph)
    failed = any(finding.severity.rank >= failure_threshold.rank for finding in findings)
    return ScanReport(
        target=target,
        status=ScanStatus.FAILED if failed else ScanStatus.PASSED,
        failure_threshold=failure_threshold,
        graph=graph,
        findings=findings,
        summary=summarize(graph, findings),
    )

async def scan_mcp_target(
    target: Any,
    *,
    display_target: str = "in-memory-mcp",
    failure_threshold: Severity = Severity.HIGH,
) -> ScanReport:
    """Scan an in-memory target; used by tests and future embedded integrations."""

    try:
        graph = await discover_mcp_target(target, display_target=display_target)
    except Exception as exc:
        return ScanReport(
            target=display_target,
            status=ScanStatus.ERROR,
            failure_threshold=failure_threshold,
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    findings = run_deterministic_checks(graph)
    failed = any(finding.severity.rank >= failure_threshold.rank for finding in findings)
    return ScanReport(
        target=display_target,
        status=ScanStatus.FAILED if failed else ScanStatus.PASSED,
        failure_threshold=failure_threshold,
        graph=graph,
        findings=findings,
        summary=summarize(graph, findings),
    )
