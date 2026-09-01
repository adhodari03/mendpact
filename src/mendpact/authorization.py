"""Credential-free OAuth metadata audit orchestration."""

from __future__ import annotations

from mendpact.domain import (
    AuthorizationAuditReport,
    PolicySnapshot,
    ScanStatus,
    Severity,
)
from mendpact.policy import apply_finding_waivers
from mendpact.security.oauth_metadata import inspect_oauth_metadata
from mendpact.security.targets import TargetPolicy, validate_target_url


async def audit_oauth_metadata(
    target: str,
    *,
    failure_threshold: Severity = Severity.HIGH,
    policy: TargetPolicy | None = None,
    applied_policy: PolicySnapshot | None = None,
) -> AuthorizationAuditReport:
    """Audit MCP OAuth discovery without loading or transmitting a credential."""

    network_policy = policy or TargetPolicy()
    try:
        await validate_target_url(target, network_policy)
        metadata, raw_findings = await inspect_oauth_metadata(
            target,
            policy=network_policy,
        )
    except Exception as exc:
        return AuthorizationAuditReport(
            target=target,
            status=ScanStatus.ERROR,
            failure_threshold=failure_threshold,
            policy=applied_policy,
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    findings = apply_finding_waivers(raw_findings, applied_policy)
    failed = any(
        finding.waiver is None and finding.severity.rank >= failure_threshold.rank
        for finding in findings
    )
    return AuthorizationAuditReport(
        target=target,
        status=ScanStatus.FAILED if failed else ScanStatus.PASSED,
        failure_threshold=failure_threshold,
        policy=applied_policy,
        metadata=metadata,
        findings=findings,
    )
