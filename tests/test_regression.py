from __future__ import annotations

import pytest

from mendpact.domain import (
    BehaviorExpectation,
    BehaviorGrade,
    BehaviorReport,
    BehaviorScenario,
    BehaviorSummary,
    BehaviorThresholds,
    BehaviorTrial,
    ConfusionEdge,
    RegressionImpact,
    ScanStatus,
    ToolCallTrace,
)
from mendpact.regression import baseline_from_report, compare_to_baseline


def _report(
    decisions: list[str],
    *,
    driver: str = "replay",
    model: str = "fixture-model",
    suite_name: str = "Behavior suite",
    scenario_id: str = "read-status",
) -> BehaviorReport:
    expected_tool = "read_status"
    scenario = BehaviorScenario(
        id=scenario_id,
        name="Read status",
        task="Read the status.",
        expectation=BehaviorExpectation(tool=expected_tool),
    )
    trials: list[BehaviorTrial] = []
    for attempt, selected_tool in enumerate(decisions, start=1):
        passed = selected_tool == expected_tool
        trials.append(
            BehaviorTrial(
                scenario=scenario,
                trace=ToolCallTrace(
                    scenario_id=scenario.id,
                    attempt=attempt,
                    provider=driver,
                    model=model,
                    available_tools=["read_status", "delete_project"],
                    selected_tool=selected_tool,
                ),
                grade=BehaviorGrade(
                    passed=passed,
                    tool_selected=True,
                    single_tool_selected=True,
                    tool_exists=True,
                    expected_tool_selected=passed,
                    arguments_valid=True,
                    expected_arguments_match=True,
                    forbidden_tool_selected=False,
                    reasons=[] if passed else ["Wrong tool."],
                ),
            )
        )
    passed_trials = sum(trial.grade.passed for trial in trials)
    confusion_count = sum(
        trial.trace.selected_tool != expected_tool for trial in trials
    )
    confusions = (
        [
            ConfusionEdge(
                intended_tool=expected_tool,
                selected_tool="delete_project",
                count=confusion_count,
            )
        ]
        if confusion_count
        else []
    )
    summary = BehaviorSummary(
        scenario_count=1,
        trial_count=len(trials),
        passed_trials=passed_trials,
        failed_trials=len(trials) - passed_trials,
        pass_rate=passed_trials / len(trials),
        confusion_edges=confusions,
    )
    return BehaviorReport(
        target="in-memory-mcp",
        status=ScanStatus.PASSED if summary.failed_trials == 0 else ScanStatus.FAILED,
        suite_name=suite_name,
        driver=driver,
        model=model,
        repetitions=len(trials),
        trials=trials,
        summary=summary,
    )


def test_creates_versioned_baseline_with_existing_failure_allowance() -> None:
    baseline = baseline_from_report(_report(["read_status", "delete_project"]))

    assert baseline.schema_version == "mendpact.baseline.v1"
    assert baseline.pass_rate == 0.5
    assert baseline.thresholds.max_failed_trials == 1
    assert baseline.scenario_ids == ["read-status"]


def test_unchanged_known_failure_passes_regression_policy() -> None:
    historical = _report(["read_status", "delete_project"])
    baseline = baseline_from_report(historical)

    compared = compare_to_baseline(
        _report(["read_status", "delete_project"]),
        baseline,
    )

    assert compared.status == ScanStatus.PASSED
    assert compared.regression is not None
    assert compared.regression.status == ScanStatus.PASSED
    assert not compared.regression.findings


def test_fails_pass_rate_drop_failed_count_and_new_confusion() -> None:
    baseline = baseline_from_report(_report(["read_status", "read_status"]))

    compared = compare_to_baseline(
        _report(["read_status", "delete_project"]),
        baseline,
    )

    assert compared.status == ScanStatus.FAILED
    assert compared.regression is not None
    failure_ids = {
        finding.rule_id
        for finding in compared.regression.findings
        if finding.impact == RegressionImpact.FAILURE
    }
    assert {"MP-BEH-102", "MP-BEH-103", "MP-BEH-104"} <= failure_ids


def test_applies_minimum_pass_rate_override() -> None:
    historical = _report(["read_status", "delete_project"])
    baseline = baseline_from_report(historical)
    policy = baseline.thresholds.model_copy(update={"min_pass_rate": 0.75})

    compared = compare_to_baseline(historical, baseline, policy)

    assert compared.status == ScanStatus.FAILED
    assert compared.regression is not None
    assert any(finding.rule_id == "MP-BEH-101" for finding in compared.regression.findings)


def test_driver_and_model_changes_warn_by_default() -> None:
    baseline = baseline_from_report(_report(["read_status"]))

    compared = compare_to_baseline(
        _report(["read_status"], driver="openai", model="new-model"),
        baseline,
    )

    assert compared.status == ScanStatus.PASSED
    assert compared.regression is not None
    assert {finding.rule_id for finding in compared.regression.findings} == {
        "MP-BEH-108",
        "MP-BEH-109",
    }
    assert all(
        finding.impact == RegressionImpact.WARNING
        for finding in compared.regression.findings
    )


def test_model_change_can_be_configured_as_failure() -> None:
    baseline = baseline_from_report(
        _report(["read_status"]),
        BehaviorThresholds(fail_on_model_change=True),
    )

    compared = compare_to_baseline(
        _report(["read_status"], model="new-model"),
        baseline,
    )

    assert compared.status == ScanStatus.FAILED
    assert compared.regression is not None
    assert compared.regression.findings[0].impact == RegressionImpact.FAILURE


def test_scenario_and_trial_count_changes_fail_comparability() -> None:
    baseline = baseline_from_report(_report(["read_status"]))

    compared = compare_to_baseline(
        _report(["read_status", "read_status"], scenario_id="read-health"),
        baseline,
    )

    assert compared.status == ScanStatus.FAILED
    assert compared.regression is not None
    assert {finding.rule_id for finding in compared.regression.findings} >= {
        "MP-BEH-106",
        "MP-BEH-107",
    }


def test_failed_comparison_cannot_be_promoted() -> None:
    baseline = baseline_from_report(_report(["read_status"]))
    compared = compare_to_baseline(_report(["delete_project"]), baseline)

    with pytest.raises(ValueError, match="cannot be promoted"):
        baseline_from_report(compared)


def test_reports_one_sided_pass_rate_statistic() -> None:
    baseline = baseline_from_report(_report(["read_status"] * 100))
    current = _report(["read_status"] * 90 + ["delete_project"] * 10)

    compared = compare_to_baseline(current, baseline)

    assert compared.regression is not None
    assert compared.regression.z_score is not None
    assert compared.regression.one_sided_p_value is not None
    assert compared.regression.one_sided_p_value < 0.01


def test_rejects_incomplete_report() -> None:
    report = _report(["read_status"])
    report.trials = []

    with pytest.raises(ValueError, match="complete behavior run"):
        baseline_from_report(report)
