"""Deliberately mixed-risk MCP server for local OpenProof development."""

from mcp.server import MCPServer

mcp = MCPServer("OpenProof Fixture")


@mcp.tool()
def read_status(component: str) -> dict[str, str]:
    """Return the health status of one named component without modifying it."""
    return {"component": component, "status": "healthy"}


@mcp.tool()
def delete_project(project_id: str) -> str:
    """Permanently delete the selected project and all of its stored artifacts."""
    return f"deleted:{project_id}"


app = mcp.streamable_http_app()
