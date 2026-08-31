"""Unified provider-free MCP guard orchestration for continuous integration."""

from __future__ import annotations

from mendpact.behavior import evaluate_capability_graph
from mendpact.contract_diff import diff_scan_reports
from mendpact.domain import (
    BehaviorSuite,
    ContractImpact,
    GuardReport,
    GuardSummary,
    PolicySnapshot,
    ReplayPlan,
    ScanReport,
    ScanStatus,
    Severity,
)
from mendpact.drivers.replay import ReplayDriver
from mendpact.scanner import scan_mcp_url
from mendpact.security.targets import TargetPolicy


def _overall_status(*statuses: ScanStatus | None) -> ScanStatus:
    present = {status for status in statuses if status is not None}
    if ScanStatus.ERROR in present:
        return ScanStatus.ERROR
    if ScanStatus.FAILED in present:
        return ScanStatus.FAILED
    return ScanStatus.PASSED


def _affected_ids(report: GuardReport) -> set[str]:
    if report.contract_diff is None:
        return set()
    return {
        scenario_id
        for change in report.contract_diff.changes
        for scenario_id in change.affected_scenarios
    }


def _filter_behavior_inputs(
    suite: BehaviorSuite,
    replay: ReplayPlan,
    affected_ids: set[str],
) -> tuple[BehaviorSuite, ReplayPlan]:
    return (
        suite.model_copy(
            update={
                "scenarios": [
                    scenario
                    for scenario in suite.scenarios
                    if scenario.id in affected_ids
                ]
            }
        ),
        replay.model_copy(
            update={
                "decisions": [
                    decision
                    for decision in replay.decisions
                    if decision.scenario_id in affected_ids
                ]
            }
        ),
    )


async def guard_mcp_url(
    target: str,
    baseline: ScanReport,
    *,
    suite: BehaviorSuite | None = None,
    replay: ReplayPlan | None = None,
    repetitions: int = 1,
    scan_failure_threshold: Severity = Severity.HIGH,
    contract_failure_threshold: ContractImpact = ContractImpact.BREAKING,
    policy: TargetPolicy | None = None,
    applied_policy: PolicySnapshot | None = None,
) -> GuardReport:
    """Scan once, compare the contract, and replay only affected scenarios."""

    scan = await scan_mcp_url(
        target,
        failure_threshold=scan_failure_threshold,
        policy=policy,
        applied_policy=applied_policy,
    )
    if scan.status == ScanStatus.ERROR or scan.graph is None:
        return GuardReport(
            target=target,
            status=ScanStatus.ERROR,
            policy=applied_policy,
            scan=scan,
            behavior_skipped_reason="The scan did not produce a capability graph.",
            summary=GuardSummary(scan_status=scan.status),
            errors=[f"scan: {error}" for error in scan.errors],
        )

    try:
        contract_diff = diff_scan_reports(
            baseline,
            scan,
            suite=suite,
            failure_threshold=contract_failure_threshold,
            policy=applied_policy,
        )
    except ValueError as exc:
        return GuardReport(
            target=target,
            status=ScanStatus.ERROR,
            policy=applied_policy,
            scan=scan,
            behavior_skipped_reason="Contract comparison could not be completed.",
            summary=GuardSummary(scan_status=scan.status),
            errors=[f"contract: {exc}"],
        )
    report = GuardReport(
        target=target,
        status=_overall_status(scan.status, contract_diff.status),
        policy=applied_policy,
        scan=scan,
        contract_diff=contract_diff,
        summary=GuardSummary(
            scan_status=scan.status,
            contract_status=contract_diff.status,
            affected_scenario_count=contract_diff.summary.affected_scenario_count,
        ),
    )
    affected_ids = _affected_ids(report)
    if suite is None or replay is None:
        report.behavior_skipped_reason = "No behavior suite and replay plan were configured."
        return report
    if not affected_ids:
        report.behavior_skipped_reason = (
            "No behavior scenarios are affected by the contract changes."
        )
        return report

    affected_suite, affected_replay = _filter_behavior_inputs(
        suite,
        replay,
        affected_ids,
    )
    try:
        driver = ReplayDriver(affected_replay)
    except ValueError as exc:
        report.status = ScanStatus.ERROR
        report.summary.behavior_status = ScanStatus.ERROR
        report.behavior_skipped_reason = "Replay data could not be configured."
        report.errors.append(f"behavior: {exc}")
        return report
    behavior = await evaluate_capability_graph(
        target,
        scan.graph,
        affected_suite,
        driver,
        repetitions,
    )
    report.behavior = behavior
    report.summary.behavior_status = behavior.status
    report.summary.evaluated_scenario_count = len(affected_suite.scenarios)
    report.status = _overall_status(scan.status, contract_diff.status, behavior.status)
    report.errors.extend(f"behavior: {error}" for error in behavior.errors)
    return report
