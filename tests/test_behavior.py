import pytest
from mcp.server import MCPServer

from mendpact.behavior import evaluate_mcp_target, replay_plan_from_report
from mendpact.domain import (
    ArgumentMatch,
    ArgumentNormalizer,
    BehaviorExpectation,
    BehaviorScenario,
    BehaviorSuite,
    CapabilityNode,
    NodeKind,
    ReplayDecision,
    ReplayPlan,
    ScanStatus,
    ToolCallTrace,
)
from mendpact.drivers.replay import ReplayDriver
from mendpact.grading import grade_tool_call


def _tool(name: str = "read_status") -> CapabilityNode:
    return CapabilityNode(
        id=f"tool:{name}",
        kind=NodeKind.TOOL,
        name=name,
        input_schema={
            "type": "object",
            "properties": {"component": {"type": "string"}},
            "required": ["component"],
            "additionalProperties": False,
        },
    )


def _scenario(
    match: ArgumentMatch = ArgumentMatch.EXACT,
    normalization: dict[str, list[ArgumentNormalizer]] | None = None,
) -> BehaviorScenario:
    return BehaviorScenario(
        id="read-api-status",
        name="Read API status",
        task="Check the API status without changing anything.",
        expectation=BehaviorExpectation(
            tool="read_status",
            arguments={"component": "api"},
            argument_match=match,
            argument_normalization=normalization or {},
            forbidden_tools=["delete_project"],
        ),
    )


def _trace(selected_tool: str | None, arguments: dict[str, object]) -> ToolCallTrace:
    return ToolCallTrace(
        scenario_id="read-api-status",
        attempt=1,
        provider="test",
        model="test-model",
        available_tools=["delete_project", "read_status"],
        selected_tool=selected_tool,
        arguments=arguments,
    )


def test_grades_expected_tool_and_valid_arguments() -> None:
    grade = grade_tool_call(_scenario(), _trace("read_status", {"component": "api"}), [_tool()])

    assert grade.passed
    assert grade.arguments_valid
    assert not grade.reasons


def test_exact_arguments_remain_case_sensitive_without_normalization() -> None:
    grade = grade_tool_call(_scenario(), _trace("read_status", {"component": "API"}), [_tool()])

    assert not grade.passed
    assert not grade.expected_arguments_match


def test_normalizes_only_an_explicit_string_path() -> None:
    trace = _trace("read_status", {"component": "  API "})
    scenario = _scenario(
        normalization={
            "/component": [ArgumentNormalizer.TRIM, ArgumentNormalizer.CASEFOLD]
        }
    )

    grade = grade_tool_call(scenario, trace, [_tool()])

    assert grade.passed
    assert grade.expected_arguments_match
    assert trace.arguments == {"component": "  API "}


def test_applies_normalization_before_subset_matching() -> None:
    scenario = _scenario(
        ArgumentMatch.SUBSET,
        normalization={"/component": [ArgumentNormalizer.CASEFOLD]},
    )

    grade = grade_tool_call(
        scenario,
        _trace("read_status", {"component": "API", "detail": True}),
        [
            CapabilityNode(
                id="tool:read_status",
                kind=NodeKind.TOOL,
                name="read_status",
                input_schema={"type": "object"},
            )
        ],
    )

    assert grade.passed


def test_rejects_non_string_actual_value_at_normalized_path() -> None:
    scenario = _scenario(
        normalization={"/component": [ArgumentNormalizer.CASEFOLD]}
    )

    grade = grade_tool_call(scenario, _trace("read_status", {"component": 7}), [_tool()])

    assert not grade.passed
    assert not grade.expected_arguments_match
    assert any("actual string value" in reason for reason in grade.reasons)


def test_reports_wrong_forbidden_tool() -> None:
    tools = [_tool(), _tool("delete_project")]
    grade = grade_tool_call(
        _scenario(),
        _trace("delete_project", {"component": "api"}),
        tools,
    )

    assert not grade.passed
    assert grade.forbidden_tool_selected
    assert any("Expected tool" in reason for reason in grade.reasons)
    assert any("forbidden" in reason for reason in grade.reasons)


def test_grades_json_schema_and_argument_match_separately() -> None:
    invalid = grade_tool_call(_scenario(), _trace("read_status", {}), [_tool()])
    subset = grade_tool_call(
        _scenario(ArgumentMatch.SUBSET),
        _trace("read_status", {"component": "api", "detail": True}),
        [
            CapabilityNode(
                id="tool:read_status",
                kind=NodeKind.TOOL,
                name="read_status",
                input_schema={"type": "object"},
            )
        ],
    )

    assert not invalid.arguments_valid
    assert not invalid.expected_arguments_match
    assert subset.passed


def test_rejects_multiple_calls_and_unparseable_arguments() -> None:
    trace = _trace("read_status", {"component": "api"})
    trace.tool_call_count = 2
    trace.arguments_parse_error = "invalid JSON"

    grade = grade_tool_call(_scenario(), trace, [_tool()])

    assert not grade.passed
    assert not grade.single_tool_selected
    assert not grade.arguments_valid
    assert any("exactly one tool call" in reason for reason in grade.reasons)
    assert any("Could not parse" in reason for reason in grade.reasons)


@pytest.mark.anyio
async def test_evaluates_replayed_decision_against_in_memory_server() -> None:
    server = MCPServer("behavior-server")

    @server.tool()
    def read_status(component: str) -> str:
        """Read the status of a component without changing state."""
        return component

    suite = BehaviorSuite(name="Read behavior", scenarios=[_scenario()])
    driver = ReplayDriver(
        ReplayPlan(
            model="fixture-model",
            decisions=[
                ReplayDecision(
                    scenario_id="read-api-status",
                    selected_tool="read_status",
                    arguments={"component": "api"},
                )
            ],
        )
    )

    report = await evaluate_mcp_target(server, suite, driver)

    assert report.status == ScanStatus.PASSED
    assert report.tool_catalog == ["read_status"]
    assert report.summary is not None
    assert report.summary.pass_rate == 1.0


@pytest.mark.anyio
async def test_summarizes_repeated_tool_confusion() -> None:
    server = MCPServer("confusion-server")

    @server.tool()
    def read_status(component: str) -> str:
        """Read component status."""
        return component

    @server.tool()
    def delete_project(component: str) -> str:
        """Delete a project."""
        return component

    suite = BehaviorSuite(name="Confusion behavior", scenarios=[_scenario()])
    driver = ReplayDriver(
        ReplayPlan(
            model="fixture-model",
            decisions=[
                ReplayDecision(
                    scenario_id="read-api-status",
                    attempt=attempt,
                    selected_tool="delete_project",
                    arguments={"component": "api"},
                )
                for attempt in (1, 2)
            ],
        )
    )

    report = await evaluate_mcp_target(server, suite, driver, repetitions=2)

    assert report.status == ScanStatus.FAILED
    assert report.summary is not None
    assert report.summary.failed_trials == 2
    assert report.summary.confusion_edges[0].count == 2


@pytest.mark.anyio
async def test_exports_complete_behavior_run_as_replay_plan() -> None:
    server = MCPServer("record-server")

    @server.tool()
    def read_status(component: str) -> str:
        """Read component status."""
        return component

    suite = BehaviorSuite(name="Record behavior", scenarios=[_scenario()])
    driver = ReplayDriver(
        ReplayPlan(
            model="fixture-model",
            decisions=[
                ReplayDecision(
                    scenario_id="read-api-status",
                    selected_tool="read_status",
                    arguments={"component": "api"},
                )
            ],
        )
    )
    report = await evaluate_mcp_target(server, suite, driver)

    replay = replay_plan_from_report(report)

    assert replay.model == "fixture-model"
    assert replay.decisions[0].selected_tool == "read_status"
