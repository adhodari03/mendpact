"""Versioned behavior baselines and deterministic regression comparison."""

from __future__ import annotations

from math import sqrt
from pathlib import Path
from statistics import NormalDist
from typing import Any

from mendpact.domain import (
    BehaviorBaseline,
    BehaviorRegression,
    BehaviorReport,
    BehaviorSummary,
    BehaviorThresholds,
    RegressionFinding,
    RegressionImpact,
    ScanStatus,
)


def load_behavior_baseline(path: Path) -> BehaviorBaseline:
    """Load and validate a versioned JSON behavior baseline."""

    return BehaviorBaseline.model_validate_json(path.read_text(encoding="utf-8"))


def baseline_from_report(
    report: BehaviorReport,
    thresholds: BehaviorThresholds | None = None,
) -> BehaviorBaseline:
    """Create a reproducible baseline from one complete behavior evaluation."""

    summary = _complete_summary(report)
    if report.regression is not None and report.regression.status == ScanStatus.FAILED:
        raise ValueError("A failed regression comparison cannot be promoted to a baseline.")
    effective_thresholds = thresholds or BehaviorThresholds()
    if effective_thresholds.max_failed_trials is None:
        effective_thresholds = effective_thresholds.model_copy(
            update={"max_failed_trials": summary.failed_trials}
        )

    return BehaviorBaseline(
        source_run_id=report.run_id,
        suite_name=report.suite_name,
        driver=report.driver,
        model=report.model,
        repetitions=report.repetitions,
        scenario_ids=sorted({trial.scenario.id for trial in report.trials}),
        trial_count=summary.trial_count,
        passed_trials=summary.passed_trials,
        failed_trials=summary.failed_trials,
        pass_rate=summary.pass_rate,
        confusion_edges=summary.confusion_edges,
        thresholds=effective_thresholds,
    )


def compare_to_baseline(
    report: BehaviorReport,
    baseline: BehaviorBaseline,
    thresholds: BehaviorThresholds | None = None,
) -> BehaviorReport:
    """Attach a regression result and make its status authoritative for CI."""

    summary = _complete_summary(report)
    policy = thresholds or baseline.thresholds
    findings: list[RegressionFinding] = []

    _check_metadata(report, baseline, policy, findings)
    _check_run_shape(report, baseline, policy, findings)
    _check_quality(summary, baseline, policy, findings)

    pass_rate_drop = max(0.0, baseline.pass_rate - summary.pass_rate)
    z_score, p_value = _one_sided_proportion_test(
        baseline.passed_trials,
        baseline.trial_count,
        summary.passed_trials,
        summary.trial_count,
    )
    status = (
        ScanStatus.FAILED
        if any(finding.impact == RegressionImpact.FAILURE for finding in findings)
        else ScanStatus.PASSED
    )
    regression = BehaviorRegression(
        status=status,
        baseline_run_id=baseline.source_run_id,
        baseline_pass_rate=baseline.pass_rate,
        current_pass_rate=summary.pass_rate,
        pass_rate_drop=pass_rate_drop,
        z_score=z_score,
        one_sided_p_value=p_value,
        thresholds=policy,
        findings=findings,
    )
    return report.model_copy(update={"status": status, "regression": regression})


def _complete_summary(report: BehaviorReport) -> BehaviorSummary:
    if report.status == ScanStatus.ERROR or report.errors:
        raise ValueError("An errored behavior run cannot be used for baseline comparison.")
    if report.summary is None or not report.trials:
        raise ValueError("A complete behavior run is required for baseline comparison.")
    if len(report.trials) != report.summary.trial_count:
        raise ValueError("Behavior report trial data does not match its summary.")
    expected_trials = report.summary.scenario_count * report.repetitions
    if report.summary.trial_count != expected_trials:
        raise ValueError("Behavior report does not contain every requested trial.")
    return report.summary


def _finding(
    rule_id: str,
    impact: RegressionImpact,
    message: str,
    baseline_value: Any,
    current_value: Any,
) -> RegressionFinding:
    return RegressionFinding(
        rule_id=rule_id,
        impact=impact,
        message=message,
        baseline_value=baseline_value,
        current_value=current_value,
    )


def _check_metadata(
    report: BehaviorReport,
    baseline: BehaviorBaseline,
    policy: BehaviorThresholds,
    findings: list[RegressionFinding],
) -> None:
    if report.suite_name != baseline.suite_name:
        findings.append(
            _finding(
                "MP-BEH-105",
                RegressionImpact.FAILURE,
                "Behavior suite name changed.",
                baseline.suite_name,
                report.suite_name,
            )
        )
    if report.driver != baseline.driver:
        findings.append(
            _finding(
                "MP-BEH-108",
                RegressionImpact.FAILURE
                if policy.fail_on_driver_change
                else RegressionImpact.WARNING,
                "Model driver changed.",
                baseline.driver,
                report.driver,
            )
        )
    if report.model != baseline.model:
        findings.append(
            _finding(
                "MP-BEH-109",
                RegressionImpact.FAILURE
                if policy.fail_on_model_change
                else RegressionImpact.WARNING,
                "Model identifier changed.",
                baseline.model,
                report.model,
            )
        )


def _check_run_shape(
    report: BehaviorReport,
    baseline: BehaviorBaseline,
    policy: BehaviorThresholds,
    findings: list[RegressionFinding],
) -> None:
    current_scenarios = sorted({trial.scenario.id for trial in report.trials})
    baseline_scenarios = sorted(set(baseline.scenario_ids))
    if current_scenarios != baseline_scenarios:
        findings.append(
            _finding(
                "MP-BEH-106",
                RegressionImpact.FAILURE
                if policy.require_same_scenarios
                else RegressionImpact.WARNING,
                "Scenario set changed, so the samples are not directly comparable.",
                baseline_scenarios,
                current_scenarios,
            )
        )
    if report.summary is not None and report.summary.trial_count != baseline.trial_count:
        findings.append(
            _finding(
                "MP-BEH-107",
                RegressionImpact.FAILURE
                if policy.require_same_trial_count
                else RegressionImpact.WARNING,
                "Trial count changed, so the samples have different sizes.",
                baseline.trial_count,
                report.summary.trial_count,
            )
        )


def _check_quality(
    summary: BehaviorSummary,
    baseline: BehaviorBaseline,
    policy: BehaviorThresholds,
    findings: list[RegressionFinding],
) -> None:
    tolerance = 1e-12
    if summary.pass_rate + tolerance < policy.min_pass_rate:
        findings.append(
            _finding(
                "MP-BEH-101",
                RegressionImpact.FAILURE,
                "Pass rate is below the configured minimum.",
                policy.min_pass_rate,
                summary.pass_rate,
            )
        )
    pass_rate_drop = max(0.0, baseline.pass_rate - summary.pass_rate)
    if pass_rate_drop > policy.max_pass_rate_drop + tolerance:
        findings.append(
            _finding(
                "MP-BEH-102",
                RegressionImpact.FAILURE,
                "Pass-rate regression exceeds the allowed drop.",
                policy.max_pass_rate_drop,
                pass_rate_drop,
            )
        )
    max_failed = (
        baseline.failed_trials
        if policy.max_failed_trials is None
        else policy.max_failed_trials
    )
    if summary.failed_trials > max_failed:
        findings.append(
            _finding(
                "MP-BEH-103",
                RegressionImpact.FAILURE,
                "Failed-trial count exceeds the configured maximum.",
                max_failed,
                summary.failed_trials,
            )
        )

    known_confusions = {
        (edge.intended_tool, edge.selected_tool) for edge in baseline.confusion_edges
    }
    current_confusions = {
        (edge.intended_tool, edge.selected_tool) for edge in summary.confusion_edges
    }
    new_confusions = sorted(current_confusions - known_confusions)
    if new_confusions and not policy.allow_new_confusions:
        findings.append(
            _finding(
                "MP-BEH-104",
                RegressionImpact.FAILURE,
                "New intended-to-selected tool confusion patterns appeared.",
                sorted(known_confusions),
                new_confusions,
            )
        )


def _one_sided_proportion_test(
    baseline_passed: int,
    baseline_trials: int,
    current_passed: int,
    current_trials: int,
) -> tuple[float | None, float | None]:
    """Return z and p for the hypothesis that the current pass rate dropped."""

    if baseline_trials <= 0 or current_trials <= 0:
        return None, None
    baseline_rate = baseline_passed / baseline_trials
    current_rate = current_passed / current_trials
    pooled_rate = (baseline_passed + current_passed) / (baseline_trials + current_trials)
    variance = pooled_rate * (1.0 - pooled_rate) * (
        (1.0 / baseline_trials) + (1.0 / current_trials)
    )
    if variance <= 0.0:
        return 0.0, 1.0
    z_score = (baseline_rate - current_rate) / sqrt(variance)
    p_value = 1.0 - NormalDist().cdf(z_score)
    return z_score, min(1.0, max(0.0, p_value))
