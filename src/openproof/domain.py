"""Core, provider-neutral data structures used by OpenProof."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class NodeKind(StrEnum):
    SERVER = "server"
    TOOL = "tool"
    RESOURCE = "resource"
    RESOURCE_TEMPLATE = "resource_template"
    PROMPT = "prompt"


class Relationship(StrEnum):
    EXPOSES = "exposes"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {
            Severity.INFO: 0,
            Severity.LOW: 1,
            Severity.MEDIUM: 2,
            Severity.HIGH: 3,
            Severity.CRITICAL: 4,
        }[self]


class ScanStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class ConformanceCheckStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"
    INFO = "INFO"


class CapabilityNode(BaseModel):
    id: str
    kind: NodeKind
    name: str
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityEdge(BaseModel):
    source: str
    target: str
    relationship: Relationship = Relationship.EXPOSES


class CapabilityGraph(BaseModel):
    target: str
    protocol: str = "mcp"
    protocol_version: str | None = None
    server_name: str | None = None
    server_version: str | None = None
    instructions: str | None = None
    nodes: list[CapabilityNode] = Field(default_factory=list)
    edges: list[CapabilityEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def nodes_of_kind(self, kind: NodeKind) -> list[CapabilityNode]:
        return [node for node in self.nodes if node.kind == kind]


class Finding(BaseModel):
    rule_id: str
    severity: Severity
    title: str
    message: str
    subject: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class ScanSummary(BaseModel):
    node_count: int
    tool_count: int
    resource_count: int
    prompt_count: int
    finding_count: int
    findings_by_severity: dict[str, int]


class ScanReport(BaseModel):
    schema_version: str = "openproof.scan.v1"
    scan_id: str = Field(default_factory=lambda: str(uuid4()))
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    target: str
    status: ScanStatus
    failure_threshold: Severity
    graph: CapabilityGraph | None = None
    findings: list[Finding] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    summary: ScanSummary | None = None


class SpecReference(BaseModel):
    id: str
    url: str | None = None


class ConformanceCheck(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str
    status: ConformanceCheckStatus
    timestamp: str | None = None
    spec_references: list[SpecReference] = Field(default_factory=list, alias="specReferences")
    details: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = Field(default=None, alias="errorMessage")
    logs: list[str] = Field(default_factory=list)


class ConformanceScenario(BaseModel):
    name: str
    artifact: str
    checks: list[ConformanceCheck] = Field(default_factory=list)


class ConformanceSummary(BaseModel):
    scenario_count: int
    check_count: int
    checks_by_status: dict[str, int]


class ConformanceReport(BaseModel):
    schema_version: str = "openproof.conformance.v1"
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    target: str
    status: ScanStatus
    runner_package: str
    runner_version: str
    command: list[str] = Field(default_factory=list)
    exit_code: int | None = None
    scenarios: list[ConformanceScenario] = Field(default_factory=list)
    summary: ConformanceSummary | None = None
    stdout: str = ""
    stderr: str = ""
    errors: list[str] = Field(default_factory=list)


def summarize(graph: CapabilityGraph, findings: list[Finding]) -> ScanSummary:
    counts = {severity.value: 0 for severity in Severity}
    for finding in findings:
        counts[finding.severity.value] += 1

    return ScanSummary(
        node_count=len(graph.nodes),
        tool_count=len(graph.nodes_of_kind(NodeKind.TOOL)),
        resource_count=len(graph.nodes_of_kind(NodeKind.RESOURCE))
        + len(graph.nodes_of_kind(NodeKind.RESOURCE_TEMPLATE)),
        prompt_count=len(graph.nodes_of_kind(NodeKind.PROMPT)),
        finding_count=len(findings),
        findings_by_severity=counts,
    )


def summarize_conformance(scenarios: list[ConformanceScenario]) -> ConformanceSummary:
    counts = {status.value: 0 for status in ConformanceCheckStatus}
    for scenario in scenarios:
        for check in scenario.checks:
            counts[check.status.value] += 1

    return ConformanceSummary(
        scenario_count=len(scenarios),
        check_count=sum(len(scenario.checks) for scenario in scenarios),
        checks_by_status=counts,
    )
