from __future__ import annotations

import json
from pathlib import Path

import pytest

from mendpact.contract_diff import diff_scan_reports, load_scan_report
from mendpact.domain import (
    BehaviorExpectation,
    BehaviorScenario,
    BehaviorSuite,
    CapabilityEdge,
    CapabilityGraph,
    CapabilityNode,
    ContractImpact,
    NodeKind,
    ScanReport,
    ScanStatus,
    Severity,
)


def _tool(
    name: str = "read_status",
    *,
    description: str = "Read component status.",
    schema: dict[str, object] | None = None,
) -> CapabilityNode:
    return CapabilityNode(
        id=f"tool:{name}",
        kind=NodeKind.TOOL,
        name=name,
        description=description,
        input_schema=schema
        or {
            "type": "object",
            "properties": {"component": {"type": "string"}},
            "required": ["component"],
            "additionalProperties": False,
        },
    )


def _report(
    *nodes: CapabilityNode,
    protocol_version: str = "2025-06-18",
    instructions: str | None = None,
) -> ScanReport:
    server = CapabilityNode(
        id="server:fixture",
        kind=NodeKind.SERVER,
        name="fixture",
    )
    return ScanReport(
        target="https://example.com/mcp",
        status=ScanStatus.PASSED,
        failure_threshold=Severity.HIGH,
        graph=CapabilityGraph(
            target="https://example.com/mcp",
            protocol_version=protocol_version,
            server_name="fixture",
            server_version="1.0.0",
            instructions=instructions,
            nodes=[server, *nodes],
        ),
    )


def _suite() -> BehaviorSuite:
    return BehaviorSuite(
        name="Blast radius",
        scenarios=[
            BehaviorScenario(
                id="read-api-status",
                name="Read API status",
                task="Read the API status.",
                expectation=BehaviorExpectation(
                    tool="read_status",
                    forbidden_tools=["delete_project"],
                ),
            ),
            BehaviorScenario(
                id="search-logs",
                name="Search logs",
                task="Search the logs.",
                expectation=BehaviorExpectation(tool="search_logs"),
            ),
        ],
    )


def test_identical_contracts_pass_without_changes() -> None:
    baseline = _report(_tool())

    report = diff_scan_reports(baseline, baseline, suite=_suite())

    assert report.schema_version == "mendpact.contract-diff.v1"
    assert report.status == ScanStatus.PASSED
    assert report.summary.change_count == 0
    assert report.summary.affected_scenario_count == 0


def test_removed_tool_is_breaking_and_maps_direct_scenarios() -> None:
    report = diff_scan_reports(_report(_tool()), _report(), suite=_suite())

    assert report.status == ScanStatus.FAILED
    change = report.changes[0]
    assert change.rule_id == "MP-DIFF-001"
    assert change.impact == ContractImpact.BREAKING
    assert change.affected_scenarios == ["read-api-status"]


def test_added_tool_is_risky_and_can_affect_every_scenario() -> None:
    baseline = _report(_tool())
    candidate = _report(_tool(), _tool("summarize_logs"))

    default_report = diff_scan_reports(baseline, candidate, suite=_suite())
    strict_report = diff_scan_reports(
        baseline,
        candidate,
        suite=_suite(),
        failure_threshold=ContractImpact.RISKY,
    )

    assert default_report.status == ScanStatus.PASSED
    assert strict_report.status == ScanStatus.FAILED
    change = strict_report.changes[0]
    assert change.rule_id == "MP-DIFF-002"
    assert change.affected_scenarios == ["read-api-status", "search-logs"]


def test_classifies_object_schema_compatibility_changes() -> None:
    baseline_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "component": {"type": "string"},
            "region": {"type": "string", "enum": ["us", "eu"]},
            "legacy": {"type": "string"},
        },
        "required": ["component"],
        "additionalProperties": False,
    }
    candidate_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "component": {"type": "string"},
            "region": {"type": "string", "enum": ["us"]},
            "detail": {"type": "boolean"},
        },
        "required": ["component", "detail"],
        "additionalProperties": True,
    }

    report = diff_scan_reports(
        _report(_tool(schema=baseline_schema)),
        _report(_tool(schema=candidate_schema)),
        suite=_suite(),
    )

    changes = {change.rule_id: change for change in report.changes}
    assert report.status == ScanStatus.FAILED
    assert changes["MP-DIFF-102"].impact == ContractImpact.BREAKING
    assert changes["MP-DIFF-103"].impact == ContractImpact.BREAKING
    assert changes["MP-DIFF-106"].impact == ContractImpact.RISKY
    assert changes["MP-DIFF-108"].impact == ContractImpact.BREAKING
    assert all(
        change.affected_scenarios == ["read-api-status"]
        for change in report.changes
    )


def test_optional_argument_and_enum_expansion_are_compatible() -> None:
    baseline_schema: dict[str, object] = {
        "type": "object",
        "properties": {"region": {"type": "string", "enum": ["us"]}},
        "required": [],
        "additionalProperties": False,
    }
    candidate_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "region": {"type": "string", "enum": ["us", "eu"]},
            "detail": {"type": "boolean"},
        },
        "required": [],
        "additionalProperties": False,
    }

    report = diff_scan_reports(
        _report(_tool(schema=baseline_schema)),
        _report(_tool(schema=candidate_schema)),
    )

    assert report.status == ScanStatus.PASSED
    assert {change.rule_id for change in report.changes} == {
        "MP-DIFF-104",
        "MP-DIFF-109",
    }
    assert all(change.impact == ContractImpact.COMPATIBLE for change in report.changes)


def test_description_and_server_instruction_changes_are_risky() -> None:
    baseline = _report(_tool(), instructions="Use read-only tools.")
    candidate = _report(
        _tool(description="Read or infer component status."),
        instructions="Choose any available tool.",
    )

    report = diff_scan_reports(
        baseline,
        candidate,
        suite=_suite(),
        failure_threshold=ContractImpact.RISKY,
    )

    assert report.status == ScanStatus.FAILED
    assert {change.rule_id for change in report.changes} == {
        "MP-DIFF-003",
        "MP-DIFF-005",
    }
    description = next(change for change in report.changes if change.rule_id == "MP-DIFF-003")
    assert description.affected_scenarios == ["read-api-status"]


def test_protocol_change_is_breaking() -> None:
    report = diff_scan_reports(
        _report(_tool(), protocol_version="2025-06-18"),
        _report(_tool(), protocol_version="2026-01-01"),
    )

    assert report.status == ScanStatus.FAILED
    assert report.changes[0].rule_id == "MP-DIFF-006"


def test_capability_identity_and_graph_edges_are_compared() -> None:
    baseline = _report(_tool())
    candidate_tool = _tool()
    candidate_tool.name = "fetch_status"
    assert baseline.graph is not None
    assert candidate_tool.id == "tool:read_status"
    baseline.graph.edges = [
        CapabilityEdge(source="server:fixture", target="tool:read_status")
    ]
    candidate = _report(candidate_tool)

    report = diff_scan_reports(baseline, candidate, suite=_suite())

    changes = {change.rule_id: change for change in report.changes}
    assert changes["MP-DIFF-004"].impact == ContractImpact.BREAKING
    assert changes["MP-DIFF-004"].affected_scenarios == ["read-api-status"]
    assert changes["MP-DIFF-010"].impact == ContractImpact.BREAKING


def test_added_graph_edge_is_compatible() -> None:
    baseline = _report(_tool())
    candidate = _report(_tool())
    assert candidate.graph is not None
    candidate.graph.edges = [
        CapabilityEdge(source="server:fixture", target="tool:read_status")
    ]

    report = diff_scan_reports(baseline, candidate)

    assert report.status == ScanStatus.PASSED
    assert report.changes[0].rule_id == "MP-DIFF-011"
    assert report.changes[0].impact == ContractImpact.COMPATIBLE


def test_boolean_property_schema_changes_are_classified() -> None:
    baseline_schema: dict[str, object] = {
        "type": "object",
        "properties": {"component": {"type": "string"}},
    }
    candidate_schema: dict[str, object] = {
        "type": "object",
        "properties": {"component": False},
    }

    report = diff_scan_reports(
        _report(_tool(schema=baseline_schema)),
        _report(_tool(schema=candidate_schema)),
    )

    assert report.status == ScanStatus.FAILED
    assert report.changes[0].rule_id == "MP-DIFF-114"
    assert report.changes[0].impact == ContractImpact.BREAKING


def test_additional_property_schema_restriction_is_breaking() -> None:
    baseline_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": True,
    }
    candidate_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }

    report = diff_scan_reports(
        _report(_tool(schema=baseline_schema)),
        _report(_tool(schema=candidate_schema)),
    )

    assert report.status == ScanStatus.FAILED
    assert report.changes[0].rule_id == "MP-DIFF-115"
    assert report.changes[0].impact == ContractImpact.BREAKING


def test_invalid_bound_change_is_reported_without_crashing() -> None:
    baseline_schema: dict[str, object] = {"type": "string", "minLength": "one"}
    candidate_schema: dict[str, object] = {"type": "string", "minLength": 2}

    report = diff_scan_reports(
        _report(_tool(schema=baseline_schema)),
        _report(_tool(schema=candidate_schema)),
        failure_threshold=ContractImpact.RISKY,
    )

    assert report.status == ScanStatus.FAILED
    assert report.changes[0].rule_id == "MP-DIFF-113"
    assert report.changes[0].impact == ContractImpact.RISKY


def test_rejects_incomplete_and_duplicate_graphs() -> None:
    incomplete = ScanReport(
        target="https://example.com/mcp",
        status=ScanStatus.ERROR,
        failure_threshold=Severity.HIGH,
        errors=["discovery failed"],
    )
    duplicate = _report(_tool(), _tool())
    duplicate_edges = _report(_tool())
    dangling_edge = _report(_tool())
    assert duplicate_edges.graph is not None
    duplicate_edges.graph.edges = [
        CapabilityEdge(source="server:fixture", target="tool:read_status"),
        CapabilityEdge(source="server:fixture", target="tool:read_status"),
    ]
    assert dangling_edge.graph is not None
    dangling_edge.graph.edges = [
        CapabilityEdge(source="server:fixture", target="tool:missing")
    ]

    with pytest.raises(ValueError, match="complete capability graph"):
        diff_scan_reports(incomplete, _report(_tool()))
    with pytest.raises(ValueError, match="duplicate capability node IDs"):
        diff_scan_reports(_report(_tool()), duplicate)
    with pytest.raises(ValueError, match="duplicate capability edges"):
        diff_scan_reports(_report(_tool()), duplicate_edges)
    with pytest.raises(ValueError, match="dangling capability edge"):
        diff_scan_reports(_report(_tool()), dangling_edge)


def test_load_rejects_unknown_scan_schema(tmp_path: Path) -> None:
    path = tmp_path / "scan.json"
    payload = json.loads(_report(_tool()).model_dump_json())
    payload["schema_version"] = "mendpact.scan.v999"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported scan schema"):
        load_scan_report(path)
