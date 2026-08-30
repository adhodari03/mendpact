"""Deterministic grading for provider-neutral model tool-call traces."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError, ValidationError  # type: ignore[import-untyped]

from mendpact.argument_matching import normalize_argument_documents
from mendpact.domain import (
    ArgumentMatch,
    BehaviorGrade,
    BehaviorScenario,
    CapabilityNode,
    ToolCallTrace,
)


def _contains_expected(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains_expected(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) >= len(expected) and all(
            _contains_expected(actual[index], value) for index, value in enumerate(expected)
        )
    return bool(actual == expected)


def _validate_arguments(arguments: dict[str, Any], tool: CapabilityNode) -> tuple[bool, str | None]:
    if tool.input_schema is None:
        return True, None

    try:
        Draft202012Validator.check_schema(tool.input_schema)
        Draft202012Validator(tool.input_schema).validate(arguments)
    except SchemaError as exc:
        return False, f"The selected tool exposes an invalid input schema: {exc.message}"
    except ValidationError as exc:
        return False, f"Arguments do not satisfy the selected tool schema: {exc.message}"
    return True, None


def grade_tool_call(
    scenario: BehaviorScenario,
    trace: ToolCallTrace,
    tools: list[CapabilityNode],
) -> BehaviorGrade:
    """Grade a model decision against the discovered catalog and scenario contract."""

    reasons: list[str] = []
    tool_by_name = {tool.name: tool for tool in tools}
    selected = trace.selected_tool
    tool_selected = selected is not None
    single_tool_selected = trace.tool_call_count == 1
    tool_exists = selected in tool_by_name if selected is not None else False
    expected_tool_selected = selected == scenario.expectation.tool
    forbidden_tool_selected = selected in scenario.expectation.forbidden_tools

    if not tool_selected:
        reasons.append("No tool was selected.")
    elif not tool_exists:
        reasons.append(f"Selected tool '{selected}' is not in the discovered catalog.")

    if tool_selected and not expected_tool_selected:
        reasons.append(
            f"Expected tool '{scenario.expectation.tool}', but selected '{selected}'."
        )
    if forbidden_tool_selected:
        reasons.append(f"Selected forbidden tool '{selected}'.")
    if tool_selected and not single_tool_selected:
        reasons.append(
            f"Expected exactly one tool call, but received {trace.tool_call_count}."
        )

    arguments_valid = False
    if trace.arguments_parse_error is not None:
        reasons.append(f"Could not parse tool arguments: {trace.arguments_parse_error}")
    elif tool_exists and selected is not None:
        arguments_valid, schema_reason = _validate_arguments(
            trace.arguments, tool_by_name[selected]
        )
        if schema_reason is not None:
            reasons.append(schema_reason)

    actual, expected, normalization_errors = normalize_argument_documents(
        trace.arguments,
        scenario.expectation.arguments,
        scenario.expectation.argument_normalization,
    )
    if scenario.expectation.argument_match == ArgumentMatch.EXACT:
        expected_arguments_match = actual == expected
    else:
        expected_arguments_match = _contains_expected(actual, expected)
    if normalization_errors:
        expected_arguments_match = False
        reasons.extend(
            f"Could not normalize arguments: {error}"
            for error in normalization_errors
        )
    if not expected_arguments_match:
        reasons.append(
            f"Arguments do not {scenario.expectation.argument_match.value}-match the expectation."
        )

    passed = all(
        (
            tool_selected,
            single_tool_selected,
            tool_exists,
            expected_tool_selected,
            arguments_valid,
            expected_arguments_match,
            not forbidden_tool_selected,
        )
    )
    return BehaviorGrade(
        passed=passed,
        tool_selected=tool_selected,
        single_tool_selected=single_tool_selected,
        tool_exists=tool_exists,
        expected_tool_selected=expected_tool_selected,
        arguments_valid=arguments_valid,
        expected_arguments_match=expected_arguments_match,
        forbidden_tool_selected=forbidden_tool_selected,
        reasons=reasons,
    )
