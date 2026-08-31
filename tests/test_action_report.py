from __future__ import annotations

from pathlib import Path

from mendpact.action_report import (
    Annotation,
    format_annotation,
    render_action_report,
    render_report_file,
)


def _scan_payload() -> dict[str, object]:
    return {
        "schema_version": "mendpact.scan.v1",
        "status": "failed",
        "target": "https://user:secret@example.com/mcp?token=hidden#fragment",
        "summary": {
            "tool_count": 2,
            "resource_count": 1,
            "prompt_count": 0,
            "finding_count": 1,
        },
        "findings": [
            {
                "severity": "high",
                "rule_id": "MP-MCP-004",
                "subject": "tool:delete|project",
                "message": "Delete <everything>\nafter approval.",
            }
        ],
        "errors": [],
    }


def test_renders_scan_summary_without_leaking_target_secrets() -> None:
    rendered = render_action_report(_scan_payload(), "reports/scan report.json")

    assert "## MendPact Scan" in rendered.summary
    assert "https://example.com/mcp" in rendered.summary
    assert "secret" not in rendered.summary
    assert "token=hidden" not in rendered.summary
    assert "tool:delete&#124;project" in rendered.summary
    assert "Delete &lt;everything&gt;<br>after approval." in rendered.summary
    assert rendered.annotations[0].level == "error"
    assert rendered.annotations[1].level == "warning"


def test_renders_guard_stages_contract_changes_and_failed_trials() -> None:
    payload: dict[str, object] = {
        "schema_version": "mendpact.guard.v1",
        "status": "failed",
        "target": "https://example.com/mcp",
        "summary": {
            "scan_status": "passed",
            "contract_status": "failed",
            "behavior_status": "failed",
            "affected_scenario_count": 1,
            "evaluated_scenario_count": 1,
        },
        "contract_diff": {
            "summary": {
                "change_count": 1,
                "changes_by_impact": {"compatible": 0, "risky": 0, "breaking": 1},
            },
            "changes": [
                {
                    "impact": "breaking",
                    "rule_id": "MP-DIFF-002",
                    "subject": "tool:read_status",
                    "message": "Required argument added.",
                    "affected_scenarios": ["read-status"],
                }
            ],
        },
        "behavior": {
            "status": "failed",
            "summary": {
                "trial_count": 1,
                "passed_trials": 0,
                "failed_trials": 1,
                "pass_rate": 0.0,
            },
            "trials": [
                {
                    "scenario": {"id": "read-status"},
                    "trace": {"selected_tool": "delete_project"},
                    "grade": {"passed": False, "reasons": ["wrong tool"]},
                }
            ],
        },
        "scan": {
            "status": "passed",
            "summary": {
                "tool_count": 2,
                "resource_count": 0,
                "prompt_count": 0,
                "finding_count": 0,
            },
            "findings": [],
        },
        "errors": [],
    }

    rendered = render_action_report(payload, "guard.json")

    assert "## MendPact Guard" in rendered.summary
    assert "### Guard stages" in rendered.summary
    assert "### Contract changes" in rendered.summary
    assert "BREAKING" in rendered.summary
    assert "read-status" in rendered.summary
    assert "delete_project" in rendered.summary
    assert "wrong tool" in rendered.summary


def test_escapes_github_workflow_annotation_commands() -> None:
    command = format_annotation(
        Annotation(
            level="warning",
            title="Rule: risky, change",
            message="100% unsafe\r\nnext line",
        )
    )

    assert command == (
        "::warning title=Rule%3A risky%2C change::100%25 unsafe%0D%0Anext line"
    )


def test_missing_report_returns_non_failing_feedback(tmp_path: Path) -> None:
    report = tmp_path / "missing.json"

    rendered = render_report_file(report)

    assert "MendPact report unavailable" in rendered.summary
    assert rendered.annotations[0].level == "warning"
    assert str(report) in rendered.annotations[0].message
