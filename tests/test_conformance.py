import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import mendpact.conformance as conformance
from mendpact.conformance import (
    ConformanceConfigurationError,
    build_command,
    load_results,
    run_server_conformance,
    validate_selection,
)
from mendpact.domain import ConformanceCheckStatus, ScanStatus
from mendpact.security.targets import TargetPolicy


def _check_payload(status: str = "SUCCESS") -> list[dict[str, object]]:
    return [
        {
            "id": "initialize-response",
            "name": "Initialize response",
            "description": "Server returned a valid initialize response.",
            "status": status,
            "timestamp": "2026-08-27T18:00:00.000Z",
            "specReferences": [
                {
                    "id": "lifecycle-initialization",
                    "url": "https://modelcontextprotocol.io/specification",
                }
            ],
        }
    ]


def test_defaults_to_safe_initialize_scenario() -> None:
    assert validate_selection(scenario=None, suite=None, allow_tool_calls=False) == (
        "server-initialize",
        None,
    )


def test_requires_authorization_for_suite() -> None:
    with pytest.raises(ConformanceConfigurationError, match="allow-tool-calls"):
        validate_selection(scenario=None, suite="active", allow_tool_calls=False)


def test_rejects_scenario_and_suite_together() -> None:
    with pytest.raises(ConformanceConfigurationError, match="cannot be used together"):
        validate_selection(
            scenario="server-initialize",
            suite="active",
            allow_tool_calls=True,
        )


def test_builds_pinned_runner_command(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.yml"
    command = build_command(
        "/usr/local/bin/npx",
        "https://example.com/mcp",
        scenario="server-initialize",
        suite=None,
        spec_version="2025-11-25",
        expected_failures=baseline,
        output_dir=Path("results"),
        verbose=True,
    )

    assert command[:4] == [
        "/usr/local/bin/npx",
        "--yes",
        "@modelcontextprotocol/conformance@0.1.16",
        "server",
    ]
    assert command[-1] == "--verbose"
    assert str(baseline) in command
    assert command[command.index("--output-dir") + 1] == "results"


def test_loads_upstream_check_artifacts(tmp_path: Path) -> None:
    artifact = tmp_path / "results/server-initialize-2026-08-27/checks.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps(_check_payload()), encoding="utf-8")

    scenarios, errors = load_results(tmp_path)

    assert errors == []
    assert len(scenarios) == 1
    assert scenarios[0].checks[0].status == ConformanceCheckStatus.SUCCESS
    assert scenarios[0].checks[0].spec_references[0].id == "lifecycle-initialization"


@pytest.mark.anyio
async def test_missing_node_is_a_setup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing_npx() -> str:
        raise ConformanceConfigurationError("Node.js and npx are required")

    monkeypatch.setattr(conformance, "_find_npx", missing_npx)
    report = await run_server_conformance(
        "http://127.0.0.1:8000/mcp",
        policy=TargetPolicy(allow_private=True, allow_insecure_http=True),
    )

    assert report.status == ScanStatus.ERROR
    assert "Node.js and npx are required" in report.errors[0]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("runner_exit", "expected_status"),
    [(0, ScanStatus.PASSED), (1, ScanStatus.FAILED)],
)
async def test_maps_runner_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    runner_exit: int,
    expected_status: ScanStatus,
) -> None:
    async def fake_find_npx() -> str:
        return "/usr/local/bin/npx"

    async def fake_run_process(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> CompletedProcess[bytes]:
        assert env["npm_config_cache"].startswith(str(cwd))
        artifact = Path(cwd) / "results/server-initialize-test/checks.json"
        artifact.parent.mkdir(parents=True)
        status = "SUCCESS" if runner_exit == 0 else "FAILURE"
        artifact.write_text(json.dumps(_check_payload(status)), encoding="utf-8")
        return CompletedProcess(command, runner_exit, stdout=b"runner output", stderr=b"")

    monkeypatch.setattr(conformance, "_find_npx", fake_find_npx)
    monkeypatch.setattr(conformance.anyio, "run_process", fake_run_process)
    report = await run_server_conformance(
        "http://127.0.0.1:8000/mcp",
        policy=TargetPolicy(allow_private=True, allow_insecure_http=True),
    )

    assert report.status == expected_status
    assert report.exit_code == runner_exit
    assert report.summary is not None
    assert report.summary.check_count == 1
