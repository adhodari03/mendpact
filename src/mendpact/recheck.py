"""Offline deterministic re-evaluation of a saved MCP capability scan."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mendpact import __version__
from mendpact.checks.rules import run_deterministic_checks
from mendpact.contract_diff import validate_scan_contract
from mendpact.domain import (
    Finding,
    PolicySnapshot,
    ScanRecheckEvidence,
    ScanReport,
    ScanStatus,
    Severity,
    summarize,
)
from mendpact.evidence import EvidenceExportError, load_evidence_source
from mendpact.policy import apply_finding_waivers

_AUTHORIZATION_RULE_PREFIX = "MP-AUTH-"


class ScanRecheckError(ValueError):
    """Safe-to-display failure while loading or re-evaluating a saved scan."""


def _finding_key(finding: Finding) -> tuple[int, str, str]:
    return (-finding.severity.rank, finding.rule_id, finding.subject or "")


def recheck_scan_report(
    source: Path,
    *,
    failure_threshold: Severity = Severity.HIGH,
    policy: PolicySnapshot | None = None,
    rechecked_at: datetime | None = None,
) -> ScanReport:
    """Apply current metadata rules to one complete saved scan without network access."""

    try:
        summary, loaded = load_evidence_source(source)
    except EvidenceExportError as exc:
        raise ScanRecheckError("Cannot recheck: source is unreadable or invalid.") from exc
    if not isinstance(loaded, ScanReport):
        raise ScanRecheckError("Only a complete mendpact.scan.v1 report can be rechecked.")
    if loaded.recheck is not None:
        raise ScanRecheckError("A rechecked report cannot be used as another recheck source.")
    try:
        graph = validate_scan_contract(loaded, "source")
    except ValueError as exc:
        raise ScanRecheckError("Only a complete mendpact.scan.v1 report can be rechecked.") from exc

    preserved_authorization = [
        finding.model_copy(update={"waiver": None})
        for finding in loaded.findings
        if finding.rule_id.startswith(_AUTHORIZATION_RULE_PREFIX)
    ]
    findings = apply_finding_waivers(
        [*preserved_authorization, *run_deterministic_checks(graph)],
        policy,
    )
    findings.sort(key=_finding_key)
    threshold = policy.scan_fail_on if policy is not None else failure_threshold
    failed = any(
        finding.waiver is None and finding.severity.rank >= threshold.rank for finding in findings
    )
    return loaded.model_copy(
        update={
            "status": ScanStatus.FAILED if failed else ScanStatus.PASSED,
            "failure_threshold": threshold,
            "policy": policy,
            "findings": findings,
            "errors": [],
            "summary": summarize(graph, findings),
            "recheck": ScanRecheckEvidence(
                source_sha256=summary.source_sha256,
                rechecked_at=rechecked_at or datetime.now(UTC),
                mendpact_version=__version__,
                source_status=loaded.status,
                preserved_authorization_finding_count=len(preserved_authorization),
            ),
        }
    )
