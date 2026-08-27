"""Safe wrapper around the official MCP server conformance runner."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import anyio
from pydantic import ValidationError

from mendpact.domain import (
    ConformanceCheck,
    ConformanceReport,
    ConformanceScenario,
    ScanStatus,
    summarize_conformance,
)
from mendpact.security.targets import TargetPolicy, validate_target_url

RUNNER_PACKAGE = "@modelcontextprotocol/conformance"
RUNNER_VERSION = "0.1.16"
MINIMUM_NODE_MAJOR = 22
SAFE_SCENARIO = "server-initialize"
SUPPORTED_SUITES = frozenset({"active", "all", "pending"})


class ConformanceConfigurationError(ValueError):
    """Raised when a requested conformance run is invalid or unsafe."""


def validate_selection(
    *,
    scenario: str | None,
    suite: str | None,
    allow_tool_calls: bool,
) -> tuple[str | None, str | None]:
    if scenario and suite:
        raise ConformanceConfigurationError("--scenario and --suite cannot be used together")
    if suite and suite not in SUPPORTED_SUITES:
        supported = ", ".join(sorted(SUPPORTED_SUITES))
        raise ConformanceConfigurationError(
            f"Unsupported suite {suite!r}; choose one of: {supported}"
        )

    selected_scenario = scenario
    if selected_scenario is None and suite is None:
        selected_scenario = SAFE_SCENARIO

    may_invoke_tools = suite is not None or selected_scenario != SAFE_SCENARIO
    if may_invoke_tools and not allow_tool_calls:
        raise ConformanceConfigurationError(
            "This conformance selection may invoke MCP tools; pass --allow-tool-calls "
            "only for an isolated test server"
        )
    return selected_scenario, suite


def build_command(
    npx: str,
    target: str,
    *,
    scenario: str | None,
    suite: str | None,
    spec_version: str | None,
    expected_failures: Path | None,
    output_dir: Path,
    verbose: bool,
) -> list[str]:
    command = [
        npx,
        "--yes",
        f"{RUNNER_PACKAGE}@{RUNNER_VERSION}",
        "server",
        "--url",
        target,
        "--output-dir",
        str(output_dir),
    ]
    if scenario:
        command.extend(("--scenario", scenario))
    if suite:
        command.extend(("--suite", suite))
    if spec_version:
        command.extend(("--spec-version", spec_version))
    if expected_failures:
        command.extend(("--expected-failures", str(expected_failures.resolve())))
    if verbose:
        command.append("--verbose")
    return command


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _node_major(version_output: str) -> int | None:
    match = re.search(r"v?(\d+)", version_output.strip())
    return int(match.group(1)) if match else None


async def _find_npx() -> str:
    node = shutil.which("node")
    npx = shutil.which("npx")
    if node is None or npx is None:
        raise ConformanceConfigurationError(
            "Node.js and npx are required for the official MCP conformance runner"
        )

    result = await anyio.run_process([node, "--version"], check=False)
    version_output = _decode(result.stdout)
    major = _node_major(version_output)
    if result.returncode != 0 or major is None:
        raise ConformanceConfigurationError("Could not determine the installed Node.js version")
    if major < MINIMUM_NODE_MAJOR:
        raise ConformanceConfigurationError(
            f"Node.js {MINIMUM_NODE_MAJOR} or newer is required; found {version_output.strip()}"
        )
    return npx


def load_results(root: Path) -> tuple[list[ConformanceScenario], list[str]]:
    scenarios: list[ConformanceScenario] = []
    errors: list[str] = []
    for artifact in sorted(root.glob("results/**/checks.json")):
        try:
            payload = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Could not read {artifact}: {type(exc).__name__}: {exc}")
            continue
        if not isinstance(payload, list):
            errors.append(f"Expected an array of checks in {artifact}")
            continue

        checks: list[ConformanceCheck] = []
        for index, item in enumerate(payload):
            try:
                checks.append(ConformanceCheck.model_validate(item))
            except ValidationError as exc:
                errors.append(f"Invalid check {index} in {artifact}: {exc}")
        scenarios.append(
            ConformanceScenario(
                name=artifact.parent.name,
                artifact=str(artifact.relative_to(root)),
                checks=checks,
            )
        )
    return scenarios, errors


async def run_server_conformance(
    target: str,
    *,
    scenario: str | None = None,
    suite: str | None = None,
    spec_version: str | None = None,
    expected_failures: Path | None = None,
    verbose: bool = False,
    allow_tool_calls: bool = False,
    policy: TargetPolicy | None = None,
) -> ConformanceReport:
    """Run the pinned official runner and normalize its per-scenario artifacts."""

    policy = policy or TargetPolicy()
    command: list[str] = []
    try:
        selected_scenario, selected_suite = validate_selection(
            scenario=scenario,
            suite=suite,
            allow_tool_calls=allow_tool_calls,
        )
        if expected_failures is not None and not expected_failures.is_file():
            raise ConformanceConfigurationError(
                f"Expected-failures file does not exist: {expected_failures}"
            )
        await validate_target_url(target, policy)
        npx = await _find_npx()
        command = build_command(
            npx,
            target,
            scenario=selected_scenario,
            suite=selected_suite,
            spec_version=spec_version,
            expected_failures=expected_failures,
            output_dir=Path("results"),
            verbose=verbose,
        )
    except Exception as exc:
        return ConformanceReport(
            target=target,
            status=ScanStatus.ERROR,
            runner_package=RUNNER_PACKAGE,
            runner_version=RUNNER_VERSION,
            command=command,
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    try:
        with TemporaryDirectory(prefix="mendpact-conformance-") as temporary_directory:
            root = Path(temporary_directory)
            environment = os.environ.copy()
            environment["npm_config_cache"] = str(root / ".npm-cache")
            environment["npm_config_update_notifier"] = "false"
            result = await anyio.run_process(
                command,
                cwd=root,
                env=environment,
                check=False,
            )
            scenarios, errors = load_results(root)
    except Exception as exc:
        return ConformanceReport(
            target=target,
            status=ScanStatus.ERROR,
            runner_package=RUNNER_PACKAGE,
            runner_version=RUNNER_VERSION,
            command=command,
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    if not scenarios:
        errors.append("The conformance runner produced no checks.json artifacts")
    if errors or result.returncode not in {0, 1}:
        status = ScanStatus.ERROR
    elif result.returncode == 1:
        status = ScanStatus.FAILED
    else:
        status = ScanStatus.PASSED

    return ConformanceReport(
        target=target,
        status=status,
        runner_package=RUNNER_PACKAGE,
        runner_version=RUNNER_VERSION,
        command=command,
        exit_code=result.returncode,
        scenarios=scenarios,
        summary=summarize_conformance(scenarios),
        stdout=_decode(result.stdout),
        stderr=_decode(result.stderr),
        errors=errors,
    )
