"""Deterministic driver for replaying previously recorded model decisions."""

from __future__ import annotations

from mendpact.domain import (
    BehaviorScenario,
    CapabilityNode,
    ReplayDecision,
    ReplayPlan,
    ToolCallTrace,
)


class ReplayDataError(ValueError):
    """Raised when a replay plan cannot supply one unambiguous decision."""


class ReplayDriver:
    """Turn versioned replay data into provider-neutral tool-call traces."""

    name = "replay"

    def __init__(self, plan: ReplayPlan) -> None:
        self.model = plan.model
        self._decisions: dict[tuple[str, int], ReplayDecision] = {}
        for decision in plan.decisions:
            key = (decision.scenario_id, decision.attempt)
            if key in self._decisions:
                raise ReplayDataError(
                    "Duplicate replay decision for "
                    f"scenario '{decision.scenario_id}', attempt {decision.attempt}."
                )
            self._decisions[key] = decision

    async def select_tool(
        self,
        scenario: BehaviorScenario,
        tools: list[CapabilityNode],
        attempt: int,
    ) -> ToolCallTrace:
        try:
            decision = self._decisions[(scenario.id, attempt)]
        except KeyError as exc:
            raise ReplayDataError(
                f"Missing replay decision for scenario '{scenario.id}', attempt {attempt}."
            ) from exc

        return ToolCallTrace(
            scenario_id=scenario.id,
            attempt=attempt,
            provider=self.name,
            model=self.model,
            available_tools=sorted(tool.name for tool in tools),
            selected_tool=decision.selected_tool,
            arguments=decision.arguments,
            message=decision.message,
        )
