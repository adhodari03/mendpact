import json
from pathlib import Path

from typer.testing import CliRunner

from mendpact.cli import app

runner = CliRunner()


def test_help_lists_main_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "conformance" in result.stdout
    assert "evaluate" in result.stdout


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
