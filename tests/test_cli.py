import json
from pathlib import Path

import pytest
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
    assert "init" in result.stdout


def test_init_creates_production_safe_scaffold(tmp_path: Path) -> None:
    project = tmp_path / "consumer"

    result = runner.invoke(
        app,
        ["init", str(project), "--target", "https://api.example.com/mcp"],
    )

    assert result.exit_code == 0
    policy = (project / "mendpact.toml").read_text(encoding="utf-8")
    workflow = (project / ".github/workflows/mendpact.yml").read_text(
        encoding="utf-8"
    )
    scenario = json.loads(
        (project / "mendpact/scenarios.example.json").read_text(encoding="utf-8")
    )
    assert 'profile = "production"' in policy
    assert "allow_private = false" in policy
    assert "allow_insecure_http = false" in policy
    assert "adhodari03/mendpact@v0.3.0" in workflow
    assert 'target: "https://api.example.com/mcp"' in workflow
    assert "mode: scan" in workflow
    assert "retention-days: 14" in workflow
    assert "EXAMPLE" in scenario["name"]
    assert (project / "mendpact/baselines/.gitkeep").is_file()
    assert "Review the example scenario" in result.stdout


def test_init_refuses_collisions_before_writing_any_file(tmp_path: Path) -> None:
    project = tmp_path / "consumer"
    project.mkdir()
    policy = project / "mendpact.toml"
    policy.write_text("owned by user\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["init", str(project), "--target", "https://api.example.com/mcp"],
    )

    assert result.exit_code == 2
    assert "Refusing to overwrite" in result.stdout
    assert policy.read_text(encoding="utf-8") == "owned by user\n"
    assert not (project / ".github/workflows/mendpact.yml").exists()


def test_init_force_replaces_only_generated_files_deterministically(tmp_path: Path) -> None:
    project = tmp_path / "consumer"
    project.mkdir()
    unrelated = project / "README.md"
    unrelated.write_text("keep me\n", encoding="utf-8")

    first = runner.invoke(
        app,
        ["init", str(project), "--target", "https://api.example.com/mcp"],
    )
    assert first.exit_code == 0
    expected = (project / "mendpact.toml").read_text(encoding="utf-8")
    (project / "mendpact.toml").write_text("changed\n", encoding="utf-8")

    second = runner.invoke(
        app,
        [
            "init",
            str(project),
            "--target",
            "https://api.example.com/mcp",
            "--force",
        ],
    )

    assert second.exit_code == 0
    assert (project / "mendpact.toml").read_text(encoding="utf-8") == expected
    assert unrelated.read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("http://api.example.com/mcp", "requires a production"),
        ("https://user:secret@api.example.com/mcp", "must not be embedded"),
        ("https://api.example.com/mcp?token=secret", "query or fragment"),
        ("https://api.example.com/mcp#section", "query or fragment"),
        ("https://api.example.com:invalid/mcp", "invalid port"),
        ("https://api.example.com/a path", "cannot contain whitespace"),
    ],
)
def test_init_rejects_targets_unsafe_to_commit(
    tmp_path: Path,
    target: str,
    message: str,
) -> None:
    project = tmp_path / "consumer"

    result = runner.invoke(app, ["init", str(project), "--target", target])

    assert result.exit_code == 2
    assert message in result.stdout
    assert not project.exists()


def test_init_quotes_next_command_for_directory_with_spaces(tmp_path: Path) -> None:
    project = tmp_path / "consumer project"

    result = runner.invoke(
        app,
        ["init", str(project), "--target", "https://api.example.com/mcp"],
    )

    assert result.exit_code == 0
    assert f"cd '{project}'" in result.stdout


def test_init_rejects_structural_collision_before_writing(tmp_path: Path) -> None:
    project = tmp_path / "consumer"
    project.mkdir()
    (project / ".github").write_text("not a directory\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["init", str(project), "--target", "https://api.example.com/mcp"],
    )

    assert result.exit_code == 2
    assert "parent is not a directory" in result.stdout
    assert not (project / "mendpact.toml").exists()


def test_init_force_refuses_to_follow_generated_file_symlink(tmp_path: Path) -> None:
    project = tmp_path / "consumer"
    project.mkdir()
    outside = tmp_path / "outside.toml"
    outside.write_text("do not replace\n", encoding="utf-8")
    (project / "mendpact.toml").symlink_to(outside)

    result = runner.invoke(
        app,
        [
            "init",
            str(project),
            "--target",
            "https://api.example.com/mcp",
            "--force",
        ],
    )

    assert result.exit_code == 2
    assert "Refusing to overwrite symlink" in result.stdout
    assert outside.read_text(encoding="utf-8") == "do not replace\n"


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


def test_policy_cannot_be_weakened_by_scan_cli_options(tmp_path: Path) -> None:
    policy = tmp_path / "mendpact.toml"
    policy.write_text(
        '\n'.join(
            [
                'schema_version = "mendpact.policy.v1"',
                'name = "production"',
                'profile = "production"',
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "scan",
            "https://example.com/mcp",
            "--policy",
            str(policy),
            "--fail-on",
            "critical",
        ],
    )

    assert result.exit_code == 2
    assert "--policy cannot be combined" in result.stdout
    assert "--fail-on" in result.stdout


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
