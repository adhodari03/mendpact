import socket
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest

from mendpact.domain import (
    CapabilityGraph,
    CapabilityNode,
    Finding,
    NodeKind,
    ScanRecheckEvidence,
    ScanReport,
    ScanStatus,
    Severity,
    summarize,
)
from mendpact.policy import load_policy
from mendpact.recheck import ScanRecheckError, recheck_scan_report

TARGET = "https://example.com/mcp"
NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def source_report() -> ScanReport:
    graph = CapabilityGraph(
        target=TARGET,
        protocol_version="2026-07-28",
        nodes=[
            CapabilityNode(id="server:mcp", kind=NodeKind.SERVER, name="mcp"),
            CapabilityNode(
                id="tool:execute",
                kind=NodeKind.TOOL,
                name="execute",
                description="Execute supplied JavaScript with an API client.",
                input_schema={
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                    "required": ["code"],
                    "additionalProperties": False,
                },
            ),
        ],
    )
    old = Finding(
        rule_id="MP-OLD-001",
        severity=Severity.LOW,
        title="Old rule",
        message="This deterministic finding should be replaced.",
    )
    authorization = Finding(
        rule_id="MP-AUTH-007",
        severity=Severity.MEDIUM,
        title="Authorization metadata warning",
        message="Network-derived evidence must remain visible but unrefreshed.",
    )
    findings = [old, authorization]
    return ScanReport(
        scan_id="source-scan",
        generated_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
        target=TARGET,
        status=ScanStatus.PASSED,
        failure_threshold=Severity.HIGH,
        graph=graph,
        findings=findings,
        summary=summarize(graph, findings),
    )


def write_source(path: Path, report: ScanReport | None = None) -> bytes:
    raw = (report or source_report()).model_dump_json(indent=2).encode()
    path.write_bytes(raw)
    return raw


def test_rechecks_current_rules_with_exact_source_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.json"
    raw = write_source(source)
    before = source.read_bytes()
    monkeypatch.setattr(socket, "socket", Mock(side_effect=AssertionError("network forbidden")))

    result = recheck_scan_report(source, rechecked_at=NOW)

    assert source.read_bytes() == before
    assert result.scan_id == "source-scan"
    assert result.generated_at == datetime(2026, 9, 7, 12, tzinfo=UTC)
    assert result.status == ScanStatus.FAILED
    assert [finding.rule_id for finding in result.findings] == [
        "MP-MCP-007",
        "MP-AUTH-007",
    ]
    assert result.summary is not None
    assert result.summary.finding_count == 2
    assert result.recheck == ScanRecheckEvidence(
        source_sha256=sha256(raw).hexdigest(),
        rechecked_at=NOW,
        mendpact_version="0.2.0",
        source_status=ScanStatus.PASSED,
        preserved_authorization_finding_count=1,
    )


def test_recheck_can_use_a_different_threshold(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    report = source_report()
    assert report.graph is not None
    report.graph.nodes = [report.graph.nodes[0]]
    report.findings = []
    report.summary = summarize(report.graph, [])
    write_source(source, report)

    result = recheck_scan_report(source, failure_threshold=Severity.CRITICAL, rechecked_at=NOW)

    assert result.status == ScanStatus.PASSED
    assert result.failure_threshold == Severity.CRITICAL
    assert result.policy is None


def test_recheck_applies_current_policy_threshold_and_waiver(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    report = source_report()
    assert report.graph is not None
    report.graph.nodes[1].id = "tool:delete_project"
    report.graph.nodes[1].name = "delete_project"
    report.graph.nodes[1].description = "Delete a project and all of its data."
    report.graph.nodes[1].input_schema = {"type": "object"}
    report.findings = []
    report.summary = summarize(report.graph, [])
    write_source(source, report)
    policy_file = tmp_path / "mendpact.toml"
    policy_file.write_text(
        """schema_version = "mendpact.policy.v1"
name = "reviewed local policy"
profile = "local"
scan_fail_on = "high"

[[waivers]]
rule_id = "MP-MCP-004"
subject = "tool:delete_project"
reason = "Deletion is isolated while the reviewed migration is completed."
approved_by = "security@example.com"
approved_on = 2026-09-01
expires_on = 2026-09-10
"""
    )
    policy = load_policy(policy_file, today=date(2026, 9, 8))

    result = recheck_scan_report(source, policy=policy, rechecked_at=NOW)

    assert result.status == ScanStatus.PASSED
    assert result.failure_threshold == Severity.HIGH
    assert result.policy == policy
    finding = next(item for item in result.findings if item.rule_id == "MP-MCP-004")
    assert finding.waiver is not None
    assert result.summary is not None
    assert result.summary.waived_finding_count == 1


def test_rejects_rechecked_source(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    write_source(source)
    result = recheck_scan_report(source, rechecked_at=NOW)
    write_source(source, result)

    with pytest.raises(ScanRecheckError, match="cannot be used"):
        recheck_scan_report(source)


def test_rejects_non_scan_and_incomplete_sources(tmp_path: Path) -> None:
    non_scan = tmp_path / "behavior.json"
    non_scan.write_text(
        '{"schema_version":"mendpact.behavior.v1","generated_at":"2026-09-08T12:00:00Z",'
        '"target":"fixture","status":"error","suite_name":"fixture","driver":"replay",'
        '"model":"fixture","repetitions":1}'
    )
    incomplete = tmp_path / "incomplete.json"
    report = source_report().model_copy(
        update={"status": ScanStatus.ERROR, "graph": None, "summary": None}
    )
    write_source(incomplete, report)

    for source in (non_scan, incomplete):
        with pytest.raises(ScanRecheckError, match=r"complete mendpact\.scan\.v1"):
            recheck_scan_report(source)


def test_invalid_source_uses_safe_error(tmp_path: Path) -> None:
    source = tmp_path / "customer-secret-name.json"
    source.write_text("not json")

    with pytest.raises(ScanRecheckError) as caught:
        recheck_scan_report(source)

    assert "customer-secret-name" not in str(caught.value)
