import pytest
from mcp.server import MCPServer

from mendpact.domain import NodeKind, ScanStatus, Severity
from mendpact.scanner import scan_mcp_target


@pytest.mark.anyio
async def test_discovers_and_scans_in_memory_mcp_server() -> None:
    server = MCPServer("test-server")

    @server.tool()
    def read_status(component: str) -> str:
        """Read the status of a component without changing any remote state."""
        return f"{component}:healthy"

    report = await scan_mcp_target(server, failure_threshold=Severity.HIGH)

    assert report.status == ScanStatus.PASSED
    assert report.graph is not None
    assert report.graph.server_name == "test-server"
    assert [node.name for node in report.graph.nodes_of_kind(NodeKind.TOOL)] == ["read_status"]
    assert report.summary is not None
    assert report.summary.tool_count == 1


@pytest.mark.anyio
async def test_high_risk_tool_fails_default_policy() -> None:
    server = MCPServer("risky-server")

    @server.tool()
    def delete_project(project_id: str) -> str:
        """Permanently delete a project and every artifact associated with it."""
        return project_id

    report = await scan_mcp_target(server, failure_threshold=Severity.HIGH)

    assert report.status == ScanStatus.FAILED
    assert any(finding.rule_id == "MP-MCP-004" for finding in report.findings)
