"""Core, provider-neutral data structures used by MendPact."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
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


class ArgumentMatch(StrEnum):
    """How expected arguments are compared with a model-produced tool call."""

    SUBSET = "subset"
    EXACT = "exact"


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
    schema_version: str = "mendpact.scan.v1"
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
    schema_version: str = "mendpact.conformance.v1"
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


class BehaviorExpectation(BaseModel):
    """The observable tool decision required for a scenario to pass."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    argument_match: ArgumentMatch = ArgumentMatch.SUBSET
    forbidden_tools: list[str] = Field(default_factory=list)


class BehaviorScenario(BaseModel):
    """A natural-language task paired with a deterministic expectation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    task: str = Field(min_length=1)
    expectation: BehaviorExpectation


class BehaviorSuite(BaseModel):
    """Portable collection of behavioral scenarios loaded by the CLI."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["mendpact.scenario.v1"] = "mendpact.scenario.v1"
    name: str = Field(min_length=1)
    scenarios: list[BehaviorScenario] = Field(min_length=1)


class ReplayDecision(BaseModel):
    """One recorded model decision used by the deterministic replay driver."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    attempt: int = Field(default=1, ge=1)
    selected_tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


class ReplayPlan(BaseModel):
    """Versioned replay input that stands in for a live model provider."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["mendpact.replay.v1"] = "mendpact.replay.v1"
    model: str = Field(min_length=1)
    decisions: list[ReplayDecision] = Field(min_length=1)


class ToolCallTrace(BaseModel):
    """Provider-neutral evidence describing one model tool-selection decision."""

    scenario_id: str
    attempt: int = Field(ge=1)
    provider: str
    model: str
    available_tools: list[str] = Field(default_factory=list)
    selected_tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


class BehaviorGrade(BaseModel):
    """Deterministic checks applied to one tool-call trace."""

    passed: bool
    tool_selected: bool
    tool_exists: bool
    expected_tool_selected: bool
    arguments_valid: bool
    expected_arguments_match: bool
    forbidden_tool_selected: bool
    reasons: list[str] = Field(default_factory=list)


class BehaviorTrial(BaseModel):
    scenario: BehaviorScenario
    trace: ToolCallTrace
    grade: BehaviorGrade


class ConfusionEdge(BaseModel):
    intended_tool: str
    selected_tool: str
    count: int = Field(ge=1)


class BehaviorSummary(BaseModel):
    scenario_count: int
    trial_count: int
    passed_trials: int
    failed_trials: int
    pass_rate: float
    confusion_edges: list[ConfusionEdge] = Field(default_factory=list)


class BehaviorReport(BaseModel):
    schema_version: Literal["mendpact.behavior.v1"] = "mendpact.behavior.v1"
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    target: str
    status: ScanStatus
    suite_name: str
    driver: str
    model: str
    repetitions: int = Field(ge=1)
    tool_catalog: list[str] = Field(default_factory=list)
    trials: list[BehaviorTrial] = Field(default_factory=list)
    summary: BehaviorSummary | None = None
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
