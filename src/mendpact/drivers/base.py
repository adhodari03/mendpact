"""Provider-neutral interface for model tool-selection drivers."""

from __future__ import annotations

from typing import Protocol

from mendpact.domain import BehaviorScenario, CapabilityNode, ToolCallTrace


class ModelDriver(Protocol):
    """Produce one normalized tool-selection trace for a behavior scenario."""

    name: str
    model: str

    async def select_tool(
        self,
        scenario: BehaviorScenario,
        tools: list[CapabilityNode],
        attempt: int,
    ) -> ToolCallTrace:
        """Select a tool without requiring the evaluation engine to know the provider."""

        ...
