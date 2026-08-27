"""MCP discovery adapter built on the official Python SDK."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from mcp import Client

from mendpact.domain import (
    CapabilityEdge,
    CapabilityGraph,
    CapabilityNode,
    NodeKind,
)


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json", exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    return {}


def _server_node_id(target: str) -> str:
    return f"server:{target}"


def _add_node(graph: CapabilityGraph, server_id: str, node: CapabilityNode) -> None:
    graph.nodes.append(node)
    graph.edges.append(CapabilityEdge(source=server_id, target=node.id))


async def _pages(method: Any) -> AsyncIterator[Any]:
    cursor: str | None = None
    while True:
        page = await method(cursor=cursor)
        yield page
        cursor = getattr(page, "next_cursor", None)
        if cursor is None:
            break


async def discover_mcp_target(
    target: str | Any,
    *,
    display_target: str | None = None,
) -> CapabilityGraph:
    """Discover tools, resources, templates, and prompts exposed by an MCP target."""

    target_name = display_target or (target if isinstance(target, str) else "in-memory-mcp")
    graph = CapabilityGraph(target=target_name)
    server_id = _server_node_id(target_name)

    async with Client(target) as client:
        server_info = client.server_info
        graph.protocol_version = str(client.protocol_version) if client.protocol_version else None
        graph.instructions = client.instructions
        graph.server_name = getattr(server_info, "name", None)
        graph.server_version = getattr(server_info, "version", None)
        graph.nodes.append(
            CapabilityNode(
                id=server_id,
                kind=NodeKind.SERVER,
                name=graph.server_name or target_name,
                description=graph.instructions,
                metadata={"version": graph.server_version} if graph.server_version else {},
            )
        )

        capabilities = client.server_capabilities
        if getattr(capabilities, "tools", None) is not None:
            async for page in _pages(client.list_tools):
                for tool in page.tools:
                    _add_node(
                        graph,
                        server_id,
                        CapabilityNode(
                            id=f"tool:{tool.name}",
                            kind=NodeKind.TOOL,
                            name=tool.name,
                            title=getattr(tool, "title", None),
                            description=getattr(tool, "description", None),
                            input_schema=getattr(tool, "input_schema", None),
                            metadata={
                                key: value
                                for key, value in _dump(tool).items()
                                if key
                                not in {
                                    "name",
                                    "title",
                                    "description",
                                    "inputSchema",
                                    "input_schema",
                                }
                            },
                        ),
                    )

        if getattr(capabilities, "resources", None) is not None:
            try:
                async for page in _pages(client.list_resources):
                    for resource in page.resources:
                        metadata = _dump(resource)
                        _add_node(
                            graph,
                            server_id,
                            CapabilityNode(
                                id=f"resource:{resource.uri}",
                                kind=NodeKind.RESOURCE,
                                name=resource.name,
                                title=getattr(resource, "title", None),
                                description=getattr(resource, "description", None),
                                metadata=metadata,
                            ),
                        )
            except Exception as exc:  # pragma: no cover - server interoperability boundary
                graph.warnings.append(f"Could not list resources: {type(exc).__name__}: {exc}")

            try:
                async for page in _pages(client.list_resource_templates):
                    for template in page.resource_templates:
                        uri_template = str(template.uri_template)
                        _add_node(
                            graph,
                            server_id,
                            CapabilityNode(
                                id=f"resource-template:{uri_template}",
                                kind=NodeKind.RESOURCE_TEMPLATE,
                                name=template.name,
                                title=getattr(template, "title", None),
                                description=getattr(template, "description", None),
                                metadata=_dump(template),
                            ),
                        )
            except Exception as exc:  # pragma: no cover - server interoperability boundary
                graph.warnings.append(
                    f"Could not list resource templates: {type(exc).__name__}: {exc}"
                )

        if getattr(capabilities, "prompts", None) is not None:
            try:
                async for page in _pages(client.list_prompts):
                    for prompt in page.prompts:
                        _add_node(
                            graph,
                            server_id,
                            CapabilityNode(
                                id=f"prompt:{prompt.name}",
                                kind=NodeKind.PROMPT,
                                name=prompt.name,
                                title=getattr(prompt, "title", None),
                                description=getattr(prompt, "description", None),
                                metadata=_dump(prompt),
                            ),
                        )
            except Exception as exc:  # pragma: no cover - server interoperability boundary
                graph.warnings.append(f"Could not list prompts: {type(exc).__name__}: {exc}")

    return graph
