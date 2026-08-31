"""Render MendPact JSON reports for the GitHub Actions user interface."""

from __future__ import annotations

import argparse
import html
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_TABLE_ROWS = 20
MAX_ANNOTATIONS = 10


@dataclass(frozen=True)
class Annotation:
    level: str
    title: str
    message: str


@dataclass(frozen=True)
class ActionReport:
    summary: str
    annotations: list[Annotation]


def _cell(value: object) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value) or "—"
    escaped = html.escape(str(value), quote=True)
    return escaped.replace("|", "&#124;").replace("\r\n", "<br>").replace("\n", "<br>")


def _safe_target(value: object) -> str:
    """Drop credentials, query parameters, and fragments from a report target."""
    if not isinstance(value, str):
        return "—"
    parts = urlsplit(value)
    if not parts.scheme or not parts.hostname:
        return value
    hostname = parts.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _status(value: object) -> str:
    labels: dict[str, str] = {
        "passed": "✅ Passed",
        "failed": "❌ Failed",
        "error": "⚠️ Error",
        "skipped": "⏭️ Skipped",
    }
    if value is None:
        return "⏭️ Skipped"
    text = str(value)
    return labels.get(text, text.title())


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = [
        f"| {' | '.join(headers)} |",
        f"| {' | '.join('---' for _ in headers)} |",
    ]
    lines.extend(f"| {' | '.join(_cell(value) for value in row)} |" for row in rows)
    return lines


def _limited_rows(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    shown = items[:MAX_TABLE_ROWS]
    return shown, len(items) - len(shown)


def _waiver_label(item: dict[str, Any]) -> str:
    waiver = item.get("waiver")
    if not isinstance(waiver, dict):
        return "Enforced"
    return f"Waived until {waiver.get('expires_on', 'unknown')}"


def _annotation_for_item(
    item: dict[str, Any],
    *,
    classification: str,
    fallback_subject: str,
    fallback_message: str,
) -> Annotation:
    waiver = item.get("waiver")
    waived = isinstance(waiver, dict)
    message_parts = [
        str(item.get("subject") or fallback_subject),
        str(item.get("message") or item.get("title") or fallback_message),
    ]
    if isinstance(waiver, dict):
        message_parts.append(
            "Waived until "
            f"{waiver.get('expires_on')} by {waiver.get('approved_by')}: "
            f"{waiver.get('reason')}"
        )
    return Annotation(
        level="notice" if waived else "warning",
        title=(
            f"MendPact {item.get('rule_id', 'finding')} "
            f"({classification}{', WAIVED' if waived else ''})"
        ),
        message=" — ".join(message_parts),
    )


def _scan_sections(scan: dict[str, Any]) -> tuple[list[str], list[Annotation]]:
    lines: list[str] = []
    annotations: list[Annotation] = []
    summary = scan.get("summary") or {}
    lines.extend(
        [
            "### Capability scan",
            "",
            *_table(
                ["Status", "Tools", "Resources", "Prompts", "Findings", "Waived"],
                [
                    [
                        _status(scan.get("status")),
                        summary.get("tool_count", 0),
                        summary.get("resource_count", 0),
                        summary.get("prompt_count", 0),
                        summary.get("finding_count", len(scan.get("findings", []))),
                        summary.get("waived_finding_count", 0),
                    ]
                ],
            ),
        ]
    )

    findings = [item for item in scan.get("findings", []) if isinstance(item, dict)]
    if findings:
        shown, omitted = _limited_rows(findings)
        lines.extend(
            [
                "",
                "#### Findings",
                "",
                *_table(
                    ["Severity", "Rule", "Subject", "Finding", "Policy"],
                    [
                        [
                            str(item.get("severity", "unknown")).upper(),
                            item.get("rule_id"),
                            item.get("subject"),
                            item.get("message") or item.get("title"),
                            _waiver_label(item),
                        ]
                        for item in shown
                    ],
                ),
            ]
        )
        if omitted:
            lines.extend(["", f"_{omitted} additional findings are available in the JSON report._"])

        for item in findings:
            severity = str(item.get("severity", "unknown")).upper()
            annotations.append(
                _annotation_for_item(
                    item,
                    classification=severity,
                    fallback_subject="MCP target",
                    fallback_message="Finding reported",
                )
            )
    return lines, annotations


def _guard_sections(payload: dict[str, Any]) -> tuple[list[str], list[Annotation]]:
    summary = payload.get("summary") or {}
    lines = [
        "### Guard stages",
        "",
        *_table(
            ["Scan", "Contract", "Behavior", "Affected scenarios", "Evaluated scenarios"],
            [
                [
                    _status(summary.get("scan_status")),
                    _status(summary.get("contract_status")),
                    _status(summary.get("behavior_status")),
                    summary.get("affected_scenario_count", 0),
                    summary.get("evaluated_scenario_count", 0),
                ]
            ],
        ),
    ]
    annotations: list[Annotation] = []

    contract = payload.get("contract_diff")
    if isinstance(contract, dict):
        contract_summary = contract.get("summary") or {}
        impact_counts = contract_summary.get("changes_by_impact") or {}
        changes = [item for item in contract.get("changes", []) if isinstance(item, dict)]
        lines.extend(
            [
                "",
                "### Contract changes",
                "",
                *_table(
                    ["Total", "Waived", "Compatible", "Risky", "Breaking"],
                    [
                        [
                            contract_summary.get("change_count", len(changes)),
                            contract_summary.get("waived_change_count", 0),
                            impact_counts.get("compatible", 0),
                            impact_counts.get("risky", 0),
                            impact_counts.get("breaking", 0),
                        ]
                    ],
                ),
            ]
        )
        if changes:
            shown, omitted = _limited_rows(changes)
            lines.extend(
                [
                    "",
                    *_table(
                        [
                            "Impact",
                            "Rule",
                            "Subject",
                            "Change",
                            "Affected scenarios",
                            "Policy",
                        ],
                        [
                            [
                                str(item.get("impact", "unknown")).upper(),
                                item.get("rule_id"),
                                item.get("subject"),
                                item.get("message"),
                                item.get("affected_scenarios", []),
                                _waiver_label(item),
                            ]
                            for item in shown
                        ],
                    ),
                ]
            )
            if omitted:
                lines.extend(
                    ["", f"_{omitted} additional changes are available in the JSON report._"]
                )
            for item in changes:
                impact = str(item.get("impact", "unknown")).upper()
                annotations.append(
                    _annotation_for_item(
                        item,
                        classification=impact,
                        fallback_subject="MCP contract",
                        fallback_message="Contract change detected",
                    )
                )

    behavior = payload.get("behavior")
    if isinstance(behavior, dict):
        behavior_summary = behavior.get("summary") or {}
        failed_trials = [
            item
            for item in behavior.get("trials", [])
            if isinstance(item, dict) and not (item.get("grade") or {}).get("passed", False)
        ]
        lines.extend(
            [
                "",
                "### Behavioral replay",
                "",
                *_table(
                    ["Status", "Trials", "Passed", "Failed", "Pass rate"],
                    [
                        [
                            _status(behavior.get("status")),
                            behavior_summary.get("trial_count", 0),
                            behavior_summary.get("passed_trials", 0),
                            behavior_summary.get("failed_trials", 0),
                            f"{float(behavior_summary.get('pass_rate', 0)):.1%}",
                        ]
                    ],
                ),
            ]
        )
        if failed_trials:
            shown, omitted = _limited_rows(failed_trials)
            lines.extend(
                [
                    "",
                    "#### Failed trials",
                    "",
                    *_table(
                        ["Scenario", "Selected tool", "Reasons"],
                        [
                            [
                                (item.get("scenario") or {}).get("id"),
                                (item.get("trace") or {}).get("selected_tool"),
                                (item.get("grade") or {}).get("reasons", []),
                            ]
                            for item in shown
                        ],
                    ),
                ]
            )
            if omitted:
                lines.extend(
                    ["", f"_{omitted} additional failed trials are available in the JSON report._"]
                )

    scan = payload.get("scan")
    if isinstance(scan, dict):
        scan_lines, scan_annotations = _scan_sections(scan)
        lines.extend(["", *scan_lines])
        annotations.extend(scan_annotations)
    return lines, annotations


def render_action_report(payload: dict[str, Any], report_path: str) -> ActionReport:
    schema = payload.get("schema_version")
    mode = "Guard" if schema == "mendpact.guard.v1" else "Scan"
    lines = [
        f"## MendPact {mode}",
        "",
        *_table(
            ["Status", "Target", "Schema", "Report"],
            [
                [
                    _status(payload.get("status")),
                    _safe_target(payload.get("target")),
                    schema,
                    report_path,
                ]
            ],
        ),
        "",
    ]
    annotations: list[Annotation] = []

    policy = payload.get("policy")
    if isinstance(policy, dict):
        waivers = [item for item in policy.get("waivers", []) if isinstance(item, dict)]
        active_waivers = sum(item.get("status") == "active" for item in waivers)
        expired_waivers = sum(item.get("status") == "expired" for item in waivers)
        lines.extend(
            [
                "### Applied policy",
                "",
                *_table(
                    [
                        "Name",
                        "Profile",
                        "Scan fails on",
                        "Contract fails on",
                        "Private targets",
                        "Insecure HTTP",
                        "Active waivers",
                        "Expired waivers",
                    ],
                    [
                        [
                            policy.get("name"),
                            policy.get("profile"),
                            policy.get("scan_fail_on"),
                            policy.get("contract_fail_on"),
                            "allowed" if policy.get("allow_private") else "blocked",
                            "allowed" if policy.get("allow_insecure_http") else "blocked",
                            active_waivers,
                            expired_waivers,
                        ]
                    ],
                ),
                "",
            ]
        )
        if waivers:
            shown, omitted = _limited_rows(waivers)
            lines.extend(
                [
                    "#### Policy waivers",
                    "",
                    *_table(
                        ["Rule", "Subject", "Status", "Expires", "Approved by", "Reason"],
                        [
                            [
                                item.get("rule_id"),
                                item.get("subject"),
                                str(item.get("status", "unknown")).upper(),
                                item.get("expires_on"),
                                item.get("approved_by"),
                                item.get("reason"),
                            ]
                            for item in shown
                        ],
                    ),
                    "",
                ]
            )
            if omitted:
                lines.extend(
                    [f"_{omitted} additional waivers are available in the JSON report._", ""]
                )

    if schema == "mendpact.guard.v1":
        section_lines, annotations = _guard_sections(payload)
        lines.extend(section_lines)
    elif schema == "mendpact.scan.v1":
        section_lines, annotations = _scan_sections(payload)
        lines.extend(section_lines)
    else:
        lines.extend(
            [
                "MendPact could not render detailed feedback for this report schema.",
                "See the JSON report for complete results.",
            ]
        )
        annotations.append(
            Annotation(
                level="warning",
                title="MendPact report schema",
                message=f"Unsupported report schema: {schema!s}",
            )
        )

    for error in payload.get("errors", []):
        annotations.append(
            Annotation(level="error", title="MendPact report error", message=str(error))
        )
    if payload.get("status") in {"failed", "error"}:
        annotations.insert(
            0,
            Annotation(
                level="error",
                title=f"MendPact {mode.lower()} {payload.get('status')}",
                message=f"Review the MendPact job summary and {report_path} for details.",
            ),
        )

    if len(annotations) > MAX_ANNOTATIONS:
        omitted = len(annotations) - MAX_ANNOTATIONS
        annotations = annotations[: MAX_ANNOTATIONS - 1]
        annotations.append(
            Annotation(
                level="notice",
                title="MendPact annotation limit",
                message=f"{omitted + 1} additional annotations are available in {report_path}.",
            )
        )
    return ActionReport(summary="\n".join(lines).rstrip() + "\n", annotations=annotations)


def _escape_command_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_command_property(value: str) -> str:
    return _escape_command_data(value).replace(":", "%3A").replace(",", "%2C")


def format_annotation(annotation: Annotation) -> str:
    title = _escape_command_property(annotation.title)
    message = _escape_command_data(annotation.message)
    return f"::{annotation.level} title={title}::{message}"


def _unavailable_report(report_path: Path, reason: str) -> ActionReport:
    summary = "\n".join(
        [
            "## MendPact report unavailable",
            "",
            f"MendPact could not render `{_cell(report_path)}`: {_cell(reason)}",
            "",
        ]
    )
    return ActionReport(
        summary=summary,
        annotations=[
            Annotation(
                level="warning",
                title="MendPact report unavailable",
                message=f"{report_path}: {reason}",
            )
        ],
    )


def render_report_file(report_path: Path) -> ActionReport:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _unavailable_report(report_path, str(exc))
    if not isinstance(payload, dict):
        return _unavailable_report(report_path, "the JSON root must be an object")
    return render_action_report(payload, str(report_path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    rendered = render_report_file(args.report)

    for annotation in rendered.annotations:
        print(format_annotation(annotation))

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(rendered.summary)


if __name__ == "__main__":
    main()
