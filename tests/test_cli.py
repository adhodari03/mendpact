from typer.testing import CliRunner

from openproof.cli import app

runner = CliRunner()


def test_help_lists_conformance_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "conformance" in result.stdout


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
