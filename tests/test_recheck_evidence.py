from datetime import UTC, datetime
from pathlib import Path

from mendpact.domain import (
    CapabilityGraph,
    CapabilityNode,
    NodeKind,
    ScanRecheckEvidence,
    ScanReport,
    ScanStatus,
    Severity,
    summarize,
)
from mendpact.evidence import EvidenceSection, EvidenceSummary, load_evidence_summary
from mendpact.sharing import _package_bytes, inspect_package


def _write_scan(path: Path, *, rechecked: bool) -> None:
    graph = CapabilityGraph(
        target="https://example.com/mcp",
        nodes=[CapabilityNode(id="server:mcp", kind=NodeKind.SERVER, name="mcp")],
    )
    report = ScanReport(
        target=graph.target,
        status=ScanStatus.PASSED,
        failure_threshold=Severity.HIGH,
        graph=graph,
        summary=summarize(graph, []),
        recheck=(
            ScanRecheckEvidence(
                source_sha256="0" * 64,
                mendpact_version="0.2.0",
                source_status=ScanStatus.PASSED,
                preserved_authorization_finding_count=0,
            )
            if rechecked
            else None
        ),
    )
    path.write_text(report.model_dump_json(), encoding="utf-8")


def test_evidence_distinguishes_live_capture_from_offline_recheck(tmp_path: Path) -> None:
    original = tmp_path / "original.json"
    rechecked = tmp_path / "rechecked.json"
    _write_scan(original, rechecked=False)
    _write_scan(rechecked, rechecked=True)

    original_summary = load_evidence_summary(original)
    rechecked_summary = load_evidence_summary(rechecked)

    assert original_summary.schema_version == "mendpact.evidence.v2"
    assert rechecked_summary.schema_version == "mendpact.evidence.v2"
    assert original_summary.sections[0].metrics["Evidence mode"] == "Live metadata capture"
    assert (
        rechecked_summary.sections[0].metrics["Evidence mode"]
        == "Offline deterministic recheck"
    )


def test_v1_scan_package_without_evidence_mode_remains_readable(tmp_path: Path) -> None:
    metrics: dict[str, int | str] = {
        "Fails on severity": "high",
        "Findings": 0,
        "Waived findings": 0,
        "Recorded errors (details withheld)": 0,
        "Info findings": 0,
        "Low findings": 0,
        "Medium findings": 0,
        "High findings": 0,
        "Critical findings": 0,
        "Tools": 1,
        "Resources": 0,
        "Prompts": 0,
    }
    summary = EvidenceSummary(
        schema_version="mendpact.evidence.v1",
        source_schema="mendpact.scan.v1",
        source_sha256="0" * 64,
        source_generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        recorded_status=ScanStatus.PASSED,
        sections=[
            EvidenceSection(
                title="Capability scan",
                status=ScanStatus.PASSED,
                metrics=metrics,
            )
        ],
    )
    package = tmp_path / "legacy.zip"
    package.write_bytes(_package_bytes(summary))

    inspected = inspect_package(package)

    assert inspected.summary.schema_version == "mendpact.evidence.v1"
    assert "Evidence mode" not in inspected.summary.sections[0].metrics
