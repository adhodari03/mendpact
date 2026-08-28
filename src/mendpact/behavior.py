"""Behavioral compatibility evaluation independent of model providers and the CLI."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from mendpact.adapters.mcp import discover_mcp_target
from mendpact.domain import (
    BehaviorReport,
    BehaviorSuite,
    BehaviorSummary,
    BehaviorTrial,
    CapabilityGraph,
    ConfusionEdge,
    NodeKind,
    ReplayPlan,
    ScanStatus,
)
from mendpact.drivers.base import ModelDriver
from mendpact.grading import grade_tool_call
from mendpact.security.targets import TargetPolicy, validate_target_url


def load_behavior_suite(path: Path) -> BehaviorSuite:
    """Load and validate a versioned JSON behavior suite."""

    return BehaviorSuite.model_validate_json(path.read_text(encoding="utf-8"))


def load_replay_plan(path: Path) -> ReplayPlan:
    """Load and validate versioned JSON replay decisions."""

    return ReplayPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _summary(suite: BehaviorSuite, trials: list[BehaviorTrial]) -> BehaviorSummary:
    passed_trials = sum(trial.grade.passed for trial in trials)
    confusion_counts = Counter(
        (trial.scenario.expectation.tool, trial.trace.selected_tool)
        for trial in trials
        if not trial.grade.passed
        and trial.trace.selected_tool is not None
        and trial.trace.selected_tool != trial.scenario.expectation.tool
    )
    confusion_edges = [
        ConfusionEdge(intended_tool=intended, selected_tool=selected, count=count)
        for (intended, selected), count in sorted(
            confusion_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
    ]
    trial_count = len(trials)
    return BehaviorSummary(
        scenario_count=len(suite.scenarios),
        trial_count=trial_count,
        passed_trials=passed_trials,
        failed_trials=trial_count - passed_trials,
        pass_rate=passed_trials / trial_count if trial_count else 0.0,
        confusion_edges=confusion_edges,
    )


async def _evaluate_graph(
    target: str,
    graph: CapabilityGraph,
    suite: BehaviorSuite,
    driver: ModelDriver,
    repetitions: int,
) -> BehaviorReport:
    tools = graph.nodes_of_kind(NodeKind.TOOL)
    trials: list[BehaviorTrial] = []
    try:
        for scenario in suite.scenarios:
            for attempt in range(1, repetitions + 1):
                trace = await driver.select_tool(scenario, tools, attempt)
                trials.append(
                    BehaviorTrial(
                        scenario=scenario,
                        trace=trace,
                        grade=grade_tool_call(scenario, trace, tools),
                    )
                )
    except Exception as exc:
        return BehaviorReport(
            target=target,
            status=ScanStatus.ERROR,
            suite_name=suite.name,
            driver=driver.name,
            model=driver.model,
            repetitions=repetitions,
            tool_catalog=sorted(tool.name for tool in tools),
            trials=trials,
            summary=_summary(suite, trials),
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    summary = _summary(suite, trials)
    return BehaviorReport(
        target=target,
        status=ScanStatus.FAILED if summary.failed_trials else ScanStatus.PASSED,
        suite_name=suite.name,
        driver=driver.name,
        model=driver.model,
        repetitions=repetitions,
        tool_catalog=sorted(tool.name for tool in tools),
        trials=trials,
        summary=summary,
    )


async def evaluate_mcp_url(
    target: str,
    suite: BehaviorSuite,
    driver: ModelDriver,
    *,
    repetitions: int = 1,
    policy: TargetPolicy | None = None,
) -> BehaviorReport:
    """Evaluate a remote MCP catalog with a provider-neutral model driver."""

    policy = policy or TargetPolicy()
    try:
        await validate_target_url(target, policy)
        graph = await discover_mcp_target(target)
    except Exception as exc:
        return BehaviorReport(
            target=target,
            status=ScanStatus.ERROR,
            suite_name=suite.name,
            driver=driver.name,
            model=driver.model,
            repetitions=repetitions,
            errors=[f"{type(exc).__name__}: {exc}"],
        )
    return await _evaluate_graph(target, graph, suite, driver, repetitions)


async def evaluate_mcp_target(
    target: Any,
    suite: BehaviorSuite,
    driver: ModelDriver,
    *,
    display_target: str = "in-memory-mcp",
    repetitions: int = 1,
) -> BehaviorReport:
    """Evaluate an in-memory target for tests and embedded integrations."""

    try:
        graph = await discover_mcp_target(target, display_target=display_target)
    except Exception as exc:
        return BehaviorReport(
            target=display_target,
            status=ScanStatus.ERROR,
            suite_name=suite.name,
            driver=driver.name,
            model=driver.model,
            repetitions=repetitions,
            errors=[f"{type(exc).__name__}: {exc}"],
        )
    return await _evaluate_graph(display_target, graph, suite, driver, repetitions)
