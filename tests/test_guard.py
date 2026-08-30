from __future__ import annotations

import pytest

from mendpact.domain import (
    BehaviorExpectation,
    BehaviorScenario,
    BehaviorSuite,
    CapabilityEdge,
    CapabilityGraph,
    CapabilityNode,
    NodeKind,
    ReplayDecision,
    ReplayPlan,
    ScanReport,
    ScanStatus,
    Severity,
)
from mendpact.guard import guard_mcp_url


def _tool(name: str, description: str) -> CapabilityNode:
    return CapabilityNode(
        id=f"tool:{name}",
        kind=NodeKind.TOOL,
        name=name,
        description=description,
        input_schema={
            "type": "object",
            "properties": {"component": {"type": "string"}},
            "required": ["component"],
            "additionalProperties": False,
        },
    )


def _scan(*, read_description: str = "Read status.") -> ScanReport:
    server = CapabilityNode(
        id="server:fixture",
        kind=NodeKind.SERVER,
        name="fixture",
    )
    tools = [
        _tool("read_status", read_description),
        _tool("search_logs", "Search logs."),
    ]
    return ScanReport(
        target="https://example.com/mcp",
        status=ScanStatus.PASSED,
        failure_threshold=Severity.HIGH,
        graph=CapabilityGraph(
            target="https://example.com/mcp",
            server_name="fixture",
            nodes=[server, *tools],
            edges=[
                CapabilityEdge(source=server.id, target=tool.id) for tool in tools
            ],
        ),
    )


def _suite() -> BehaviorSuite:
    return BehaviorSuite(
        name="Guard behavior",
        scenarios=[
            BehaviorScenario(
                id="read-status",
                name="Read status",
                task="Read API status.",
                expectation=BehaviorExpectation(
                    tool="read_status",
                    arguments={"component": "api"},
                ),
            ),
            BehaviorScenario(
                id="search-logs",
                name="Search logs",
                task="Search API logs.",
                expectation=BehaviorExpectation(
                    tool="search_logs",
                    arguments={"component": "api"},
                ),
            ),
        ],
    )


def _replay(*, selected_tool: str = "read_status") -> ReplayPlan:
    return ReplayPlan(
        model="guard-replay",
        decisions=[
            ReplayDecision(
                scenario_id="read-status",
                selected_tool=selected_tool,
                arguments={"component": "api"},
            ),
            ReplayDecision(
                scenario_id="search-logs",
                selected_tool="search_logs",
                arguments={"component": "api"},
            ),
        ],
    )


@pytest.mark.anyio
async def test_replays_only_scenarios_affected_by_contract_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _scan()
    candidate = _scan(read_description="Read current component status.")

    async def fake_scan(*args: object, **kwargs: object) -> ScanReport:
        return candidate

    monkeypatch.setattr("mendpact.guard.scan_mcp_url", fake_scan)

    report = await guard_mcp_url(
        "https://example.com/mcp",
        baseline,
        suite=_suite(),
        replay=_replay(),
    )

    assert report.schema_version == "mendpact.guard.v1"
    assert report.status == ScanStatus.PASSED
    assert report.summary.affected_scenario_count == 1
    assert report.summary.evaluated_scenario_count == 1
    assert report.behavior is not None
    assert [trial.scenario.id for trial in report.behavior.trials] == ["read-status"]


@pytest.mark.anyio
async def test_behavior_failure_fails_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _scan()
    candidate = _scan(read_description="Read current component status.")

    async def fake_scan(*args: object, **kwargs: object) -> ScanReport:
        return candidate

    monkeypatch.setattr("mendpact.guard.scan_mcp_url", fake_scan)

    report = await guard_mcp_url(
        "https://example.com/mcp",
        baseline,
        suite=_suite(),
        replay=_replay(selected_tool="search_logs"),
    )

    assert report.status == ScanStatus.FAILED
    assert report.summary.contract_status == ScanStatus.PASSED
    assert report.summary.behavior_status == ScanStatus.FAILED


@pytest.mark.anyio
async def test_skips_replay_when_contract_has_no_affected_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _scan()

    async def fake_scan(*args: object, **kwargs: object) -> ScanReport:
        return candidate

    monkeypatch.setattr("mendpact.guard.scan_mcp_url", fake_scan)

    report = await guard_mcp_url(
        "https://example.com/mcp",
        candidate,
        suite=_suite(),
        replay=_replay(),
    )

    assert report.status == ScanStatus.PASSED
    assert report.behavior is None
    assert report.summary.evaluated_scenario_count == 0
    assert "No behavior scenarios" in (report.behavior_skipped_reason or "")


@pytest.mark.anyio
async def test_scan_error_stops_later_guard_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_scan = ScanReport(
        target="https://example.com/mcp",
        status=ScanStatus.ERROR,
        failure_threshold=Severity.HIGH,
        errors=["connection failed"],
    )

    async def fake_scan(*args: object, **kwargs: object) -> ScanReport:
        return failed_scan

    monkeypatch.setattr("mendpact.guard.scan_mcp_url", fake_scan)

    report = await guard_mcp_url("https://example.com/mcp", _scan())

    assert report.status == ScanStatus.ERROR
    assert report.contract_diff is None
    assert report.errors == ["scan: connection failed"]


@pytest.mark.anyio
async def test_invalid_baseline_becomes_contract_stage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _scan()
    incomplete_baseline = ScanReport(
        target="https://example.com/mcp",
        status=ScanStatus.ERROR,
        failure_threshold=Severity.HIGH,
        errors=["baseline discovery failed"],
    )

    async def fake_scan(*args: object, **kwargs: object) -> ScanReport:
        return candidate

    monkeypatch.setattr("mendpact.guard.scan_mcp_url", fake_scan)

    report = await guard_mcp_url(
        "https://example.com/mcp",
        incomplete_baseline,
    )

    assert report.status == ScanStatus.ERROR
    assert report.summary.contract_status is None
    assert report.errors[0].startswith("contract:")
