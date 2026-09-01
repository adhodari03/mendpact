from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "run-action.sh"


def _run_action_script(
    tmp_path: Path,
    **inputs: str,
) -> subprocess.CompletedProcess[str]:
    executable = tmp_path / "mendpact"
    capture = tmp_path / "arguments.json"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "CAPTURE": str(capture),
        **inputs,
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=environment,
    )


def _arguments(tmp_path: Path) -> list[str]:
    return json.loads((tmp_path / "arguments.json").read_text(encoding="utf-8"))


def test_action_script_preserves_backward_compatible_scan_mode(tmp_path: Path) -> None:
    result = _run_action_script(
        tmp_path,
        MENDPACT_TARGET="https://example.com/mcp",
        MENDPACT_OUTPUT="scan report.json",
        MENDPACT_FAIL_ON="medium",
    )

    assert result.returncode == 0
    assert _arguments(tmp_path) == [
        "scan",
        "https://example.com/mcp",
        "--fail-on",
        "medium",
        "--output",
        "scan report.json",
    ]


def test_action_script_builds_guard_command_without_losing_spaces(tmp_path: Path) -> None:
    result = _run_action_script(
        tmp_path,
        MENDPACT_MODE="guard",
        MENDPACT_TARGET="http://127.0.0.1:8000/mcp",
        MENDPACT_BASELINE="contracts/reviewed baseline.json",
        MENDPACT_SCENARIO="scenarios/core suite.json",
        MENDPACT_REPLAY="replays/core decisions.json",
        MENDPACT_REPETITIONS="3",
        MENDPACT_SCAN_FAIL_ON="critical",
        MENDPACT_CONTRACT_FAIL_ON="risky",
        MENDPACT_OUTPUT="reports/guard report.json",
        MENDPACT_SAVE_SCAN="reports/candidate scan.json",
        MENDPACT_ALLOW_PRIVATE="true",
        MENDPACT_ALLOW_INSECURE_HTTP="true",
    )

    assert result.returncode == 0
    assert _arguments(tmp_path) == [
        "guard",
        "http://127.0.0.1:8000/mcp",
        "--baseline",
        "contracts/reviewed baseline.json",
        "--repetitions",
        "3",
        "--scan-fail-on",
        "critical",
        "--contract-fail-on",
        "risky",
        "--output",
        "reports/guard report.json",
        "--scenario",
        "scenarios/core suite.json",
        "--replay",
        "replays/core decisions.json",
        "--save-scan",
        "reports/candidate scan.json",
        "--allow-private",
        "--allow-insecure-http",
    ]


def test_action_script_rejects_incomplete_guard_configuration(tmp_path: Path) -> None:
    result = _run_action_script(
        tmp_path,
        MENDPACT_MODE="guard",
        MENDPACT_TARGET="https://example.com/mcp",
        MENDPACT_BASELINE="baseline.json",
        MENDPACT_SCENARIO="scenario.json",
    )

    assert result.returncode == 2
    assert "scenario and replay must be supplied together" in result.stderr
    assert not (tmp_path / "arguments.json").exists()


def test_action_script_rejects_unknown_mode_and_boolean(tmp_path: Path) -> None:
    unknown_mode = _run_action_script(
        tmp_path,
        MENDPACT_MODE="publish",
        MENDPACT_TARGET="https://example.com/mcp",
    )
    invalid_boolean = _run_action_script(
        tmp_path,
        MENDPACT_TARGET="https://example.com/mcp",
        MENDPACT_ALLOW_PRIVATE="yes",
    )

    assert unknown_mode.returncode == 2
    assert "mode must be 'scan' or 'guard'" in unknown_mode.stderr
    assert invalid_boolean.returncode == 2
    assert "must be 'true' or 'false'" in invalid_boolean.stderr


def test_action_script_lets_policy_own_guard_thresholds(tmp_path: Path) -> None:
    result = _run_action_script(
        tmp_path,
        MENDPACT_MODE="guard",
        MENDPACT_TARGET="https://example.com/mcp",
        MENDPACT_BASELINE="baseline.json",
        MENDPACT_POLICY="mendpact.toml",
        MENDPACT_OUTPUT="guard.json",
    )

    assert result.returncode == 0
    assert _arguments(tmp_path) == [
        "guard",
        "https://example.com/mcp",
        "--baseline",
        "baseline.json",
        "--repetitions",
        "1",
        "--output",
        "guard.json",
        "--policy",
        "mendpact.toml",
    ]


def test_action_script_rejects_policy_with_target_allowances(tmp_path: Path) -> None:
    result = _run_action_script(
        tmp_path,
        MENDPACT_TARGET="https://example.com/mcp",
        MENDPACT_POLICY="mendpact.toml",
        MENDPACT_ALLOW_PRIVATE="true",
    )

    assert result.returncode == 2
    assert "policy cannot be combined with target allowance inputs" in result.stderr


def test_action_script_passes_only_bearer_environment_variable_name(
    tmp_path: Path,
) -> None:
    result = _run_action_script(
        tmp_path,
        MENDPACT_TARGET="https://example.com/mcp",
        MENDPACT_AUTH_TOKEN_ENV="MENDPACT_ACCESS_TOKEN",
        MENDPACT_ACCESS_TOKEN="secret-value-never-passed-as-an-argument",
    )

    assert result.returncode == 0
    arguments = _arguments(tmp_path)
    assert arguments[-2:] == ["--auth-token-env", "MENDPACT_ACCESS_TOKEN"]
    assert "secret-value-never-passed-as-an-argument" not in arguments


def test_action_script_rejects_policy_with_authentication_input(tmp_path: Path) -> None:
    result = _run_action_script(
        tmp_path,
        MENDPACT_TARGET="https://example.com/mcp",
        MENDPACT_POLICY="mendpact.toml",
        MENDPACT_AUTH_TOKEN_ENV="MENDPACT_ACCESS_TOKEN",
    )

    assert result.returncode == 2
    assert "policy cannot be combined with auth-token-env" in result.stderr
