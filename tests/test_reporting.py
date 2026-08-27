import json
from pathlib import Path

from mendpact.domain import ConformanceReport, ScanReport, ScanStatus, Severity
from mendpact.reporting import write_conformance_report, write_json_report


def test_writes_versioned_json_report(tmp_path: Path) -> None:
    destination = tmp_path / "report.json"
    report = ScanReport(
        target="https://example.com/mcp",
        status=ScanStatus.PASSED,
        failure_threshold=Severity.HIGH,
    )

    write_json_report(report, destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "mendpact.scan.v1"
    assert payload["status"] == "passed"


def test_writes_versioned_conformance_report(tmp_path: Path) -> None:
    destination = tmp_path / "conformance.json"
    report = ConformanceReport(
        target="https://example.com/mcp",
        status=ScanStatus.PASSED,
        runner_package="@modelcontextprotocol/conformance",
        runner_version="0.1.16",
    )

    write_conformance_report(report, destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "mendpact.conformance.v1"
    assert payload["runner_version"] == "0.1.16"
