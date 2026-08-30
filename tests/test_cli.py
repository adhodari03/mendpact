import json
from pathlib import Path

from typer.testing import CliRunner

from mendpact.cli import app
from mendpact.domain import (
    CapabilityGraph,
    CapabilityNode,
    NodeKind,
    ScanReport,
    ScanStatus,
    Severity,
)

runner = CliRunner()


def test_help_lists_main_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "conformance" in result.stdout
    assert "evaluate" in result.stdout
    assert "diff" in result.stdout
    assert "guard" in result.stdout


def test_suite_requires_explicit_tool_call_authorization() -> None:
    result = runner.invoke(
        app,
        ["conformance", "https://example.com/mcp", "--suite", "active"],
    )

    assert result.exit_code == 2
    assert "allow-tool-calls" in result.stdout


def test_scenario_and_suite_are_mutually_exclusive() -> None:
    result = runner.invoke(
        app,
        [
            "conformance",
            "https://example.com/mcp",
            "--scenario",
            "server-initialize",
            "--suite",
            "active",
            "--allow-tool-calls",
        ],
    )

    assert result.exit_code == 2
    assert "--scenario and --suite" in result.stdout
    assert "cannot be used" in result.stdout


def _write_scenario(tmp_path: Path) -> Path:
    path = tmp_path / "scenario.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "mendpact.scenario.v1",
                "name": "CLI behavior",
                "scenarios": [
                    {
                        "id": "read-status",
                        "name": "Read status",
                        "task": "Read the status.",
                        "expectation": {"tool": "read_status"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_replay(tmp_path: Path) -> Path:
    path = tmp_path / "replay.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "mendpact.replay.v1",
                "model": "fixture-model",
                "decisions": [{"scenario_id": "read-status"}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_replay_driver_requires_replay_file(tmp_path: Path) -> None:
    scenario = _write_scenario(tmp_path)

    result = runner.invoke(
        app,
        ["evaluate", "https://example.com/mcp", "--scenario", str(scenario)],
    )

    assert result.exit_code == 2
    assert "--replay is required" in result.stdout


def test_openai_driver_requires_explicit_model(tmp_path: Path) -> None:
    scenario = _write_scenario(tmp_path)

    result = runner.invoke(
        app,
        [
            "evaluate",
            "https://example.com/mcp",
            "--scenario",
            str(scenario),
            "--driver",
            "openai",
        ],
    )

    assert result.exit_code == 2
    assert "--model is required" in result.stdout


def test_behavior_threshold_requires_baseline_destination(tmp_path: Path) -> None:
    scenario = _write_scenario(tmp_path)
    replay = _write_replay(tmp_path)

    result = runner.invoke(
        app,
        [
            "evaluate",
            "https://example.com/mcp",
            "--scenario",
            str(scenario),
            "--replay",
            str(replay),
            "--min-pass-rate",
            "0.9",
        ],
    )

    assert result.exit_code == 2
    assert "Behavior thresholds require --baseline" in result.stdout
    assert "--save-baseline" in result.stdout


def _write_scan(
    tmp_path: Path,
    name: str,
    *,
    include_tool: bool,
) -> Path:
    nodes = (
        [
            CapabilityNode(
                id="tool:read_status",
                kind=NodeKind.TOOL,
                name="read_status",
                input_schema={"type": "object"},
            )
        ]
        if include_tool
        else []
    )
    report = ScanReport(
        target=f"https://{name}.example/mcp",
        status=ScanStatus.PASSED,
        failure_threshold=Severity.HIGH,
        graph=CapabilityGraph(target=name, nodes=nodes),
    )
    path = tmp_path / f"{name}.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    return path


def test_contract_diff_command_writes_report_and_fails_on_breaking_change(
    tmp_path: Path,
) -> None:
    baseline = _write_scan(tmp_path, "baseline", include_tool=True)
    candidate = _write_scan(tmp_path, "candidate", include_tool=False)
    output = tmp_path / "diff.json"

    result = runner.invoke(
        app,
        ["diff", str(baseline), str(candidate), "--output", str(output)],
    )

    assert result.exit_code == 1
    assert "MendPact contract diff: FAILED" in result.stdout
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == (
        "mendpact.contract-diff.v1"
    )


def test_guard_requires_scenario_and_replay_together(tmp_path: Path) -> None:
    baseline = _write_scan(tmp_path, "baseline", include_tool=True)
    scenario = _write_scenario(tmp_path)

    result = runner.invoke(
        app,
        [
            "guard",
            "https://example.com/mcp",
            "--baseline",
            str(baseline),
            "--scenario",
            str(scenario),
        ],
    )

    assert result.exit_code == 2
    assert "--scenario and --replay must be supplied together" in result.stdout


def test_guard_does_not_overwrite_baseline(tmp_path: Path) -> None:
    baseline = _write_scan(tmp_path, "baseline", include_tool=True)

    result = runner.invoke(
        app,
        [
            "guard",
            "https://example.com/mcp",
            "--baseline",
            str(baseline),
            "--save-scan",
            str(baseline),
        ],
    )

    assert result.exit_code == 2
    assert "cannot overwrite a guard input file" in result.stdout
