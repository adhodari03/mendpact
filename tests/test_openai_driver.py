from types import SimpleNamespace
from typing import Any

import pytest

from mendpact.domain import (
    BehaviorExpectation,
    BehaviorScenario,
    CapabilityNode,
    NodeKind,
)
from mendpact.drivers.openai import (
    OpenAIDriverConfigurationError,
    OpenAIResponsesDriver,
)


class FakeResponses:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.request: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.request = kwargs
        return self.response


class FakeClient:
    def __init__(self, response: Any) -> None:
        self.responses = FakeResponses(response)


def _scenario() -> BehaviorScenario:
    return BehaviorScenario(
        id="read-api-status",
        name="Read API status",
        task="Check the API status.",
        expectation=BehaviorExpectation(
            tool="read_status",
            arguments={"component": "api"},
        ),
    )


def _tool(*, strict_compatible: bool = True) -> CapabilityNode:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"component": {"type": "string"}},
        "required": ["component"] if strict_compatible else [],
        "additionalProperties": False,
    }
    return CapabilityNode(
        id="tool:read_status",
        kind=NodeKind.TOOL,
        name="read_status",
        description="Read component status.",
        input_schema=schema,
    )


@pytest.mark.anyio
async def test_normalizes_responses_function_call_without_executing_tool() -> None:
    response = SimpleNamespace(
        id="resp_123",
        model="gpt-test-2026-08-01",
        output=[
            SimpleNamespace(
                type="function_call",
                name="read_status",
                arguments='{"component":"api"}',
            )
        ],
        output_text="",
        usage=SimpleNamespace(input_tokens=20, output_tokens=5, total_tokens=25),
    )
    client = FakeClient(response)
    driver = OpenAIResponsesDriver("gpt-test", client=client)

    trace = await driver.select_tool(_scenario(), [_tool()], 1)

    assert trace.selected_tool == "read_status"
    assert trace.arguments == {"component": "api"}
    assert trace.tool_call_count == 1
    assert trace.response_id == "resp_123"
    assert trace.model == "gpt-test-2026-08-01"
    assert trace.total_tokens == 25
    assert trace.latency_ms is not None
    assert client.responses.request["tool_choice"] == "required"
    assert client.responses.request["parallel_tool_calls"] is False
    assert client.responses.request["store"] is False
    assert client.responses.request["tools"][0]["strict"] is True


@pytest.mark.anyio
async def test_marks_non_strict_mcp_schema_and_argument_parse_failure() -> None:
    response = SimpleNamespace(
        id="resp_bad",
        model="gpt-test",
        output=[
            SimpleNamespace(
                type="function_call",
                name="read_status",
                arguments="not-json",
            )
        ],
        output_text="",
        usage=None,
    )
    client = FakeClient(response)
    driver = OpenAIResponsesDriver("gpt-test", client=client)

    trace = await driver.select_tool(_scenario(), [_tool(strict_compatible=False)], 1)

    assert trace.arguments == {}
    assert trace.arguments_parse_error is not None
    assert client.responses.request["tools"][0]["strict"] is False


@pytest.mark.anyio
async def test_maps_provider_safe_name_back_to_original_mcp_tool() -> None:
    response = SimpleNamespace(
        id="resp_alias",
        model="gpt-test",
        output=[],
        output_text="",
        usage=None,
    )
    client = FakeClient(response)
    driver = OpenAIResponsesDriver("gpt-test", client=client)
    tool = _tool()
    tool.id = "tool:status.read"
    tool.name = "status.read"

    first_trace = await driver.select_tool(_scenario(), [tool], 1)
    provider_name = client.responses.request["tools"][0]["name"]
    response.output = [
        SimpleNamespace(
            type="function_call",
            name=provider_name,
            arguments='{"component":"api"}',
        )
    ]
    second_trace = await driver.select_tool(_scenario(), [tool], 2)

    assert first_trace.selected_tool is None
    assert "." not in provider_name
    assert second_trace.selected_tool == "status.read"
    assert second_trace.provider_selected_tool == provider_name


def test_requires_api_key_for_real_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(OpenAIDriverConfigurationError, match="OPENAI_API_KEY"):
        OpenAIResponsesDriver("gpt-test")
