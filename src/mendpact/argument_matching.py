"""Explicit, deterministic normalization for expected tool arguments."""

from __future__ import annotations

from copy import deepcopy
from enum import StrEnum
from typing import Any


class ArgumentNormalizer(StrEnum):
    """Supported string transformations for one configured argument path."""

    TRIM = "trim"
    CASEFOLD = "casefold"


class ArgumentNormalizationError(ValueError):
    """Raised when a normalization rule cannot address a string value."""


def _pointer_tokens(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise ArgumentNormalizationError(
            f"JSON Pointer '{pointer}' must start with '/'."
        )

    tokens: list[str] = []
    for raw_token in pointer[1:].split("/"):
        token = ""
        index = 0
        while index < len(raw_token):
            character = raw_token[index]
            if character != "~":
                token += character
                index += 1
                continue
            if index + 1 >= len(raw_token) or raw_token[index + 1] not in {"0", "1"}:
                raise ArgumentNormalizationError(
                    f"JSON Pointer '{pointer}' contains an invalid '~' escape."
                )
            token += "~" if raw_token[index + 1] == "0" else "/"
            index += 2
        tokens.append(token)
    return tokens


def _list_index(token: str, pointer: str) -> int:
    if token == "0":
        return 0
    if token.isdigit() and not token.startswith("0"):
        return int(token)
    raise ArgumentNormalizationError(
        f"JSON Pointer '{pointer}' uses invalid array index '{token}'."
    )


def _value_at_pointer(document: Any, pointer: str) -> Any:
    current = document
    for token in _pointer_tokens(pointer):
        if isinstance(current, dict):
            if token not in current:
                raise ArgumentNormalizationError(
                    f"JSON Pointer '{pointer}' does not exist in the arguments."
                )
            current = current[token]
        elif isinstance(current, list):
            list_index = _list_index(token, pointer)
            if list_index >= len(current):
                raise ArgumentNormalizationError(
                    f"JSON Pointer '{pointer}' is outside the argument array."
                )
            current = current[list_index]
        else:
            raise ArgumentNormalizationError(
                f"JSON Pointer '{pointer}' traverses a non-container value."
            )
    return current


def _replace_at_pointer(document: Any, pointer: str, value: str) -> None:
    tokens = _pointer_tokens(pointer)
    current = document
    for token in tokens[:-1]:
        if isinstance(current, dict):
            current = current[token]
        else:
            current = current[_list_index(token, pointer)]

    final_token = tokens[-1]
    if isinstance(current, dict):
        current[final_token] = value
    else:
        current[_list_index(final_token, pointer)] = value


def _normalize_string(value: str, operations: list[ArgumentNormalizer]) -> str:
    normalized = value
    for operation in operations:
        if operation == ArgumentNormalizer.TRIM:
            normalized = normalized.strip()
        elif operation == ArgumentNormalizer.CASEFOLD:
            normalized = normalized.casefold()
    return normalized


def normalization_configuration_errors(
    expected: dict[str, Any],
    rules: dict[str, list[ArgumentNormalizer]],
) -> list[str]:
    """Validate that every rule is meaningful for the expected argument contract."""

    errors: list[str] = []
    for pointer, operations in rules.items():
        if not operations:
            errors.append(f"JSON Pointer '{pointer}' must configure at least one normalizer.")
            continue
        if len(set(operations)) != len(operations):
            errors.append(f"JSON Pointer '{pointer}' contains duplicate normalizers.")
        try:
            expected_value = _value_at_pointer(expected, pointer)
        except ArgumentNormalizationError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(expected_value, str):
            errors.append(f"JSON Pointer '{pointer}' must target an expected string value.")
    return errors


def normalize_argument_documents(
    actual: dict[str, Any],
    expected: dict[str, Any],
    rules: dict[str, list[ArgumentNormalizer]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Return normalized copies while retaining every raw value in the trace."""

    normalized_actual = deepcopy(actual)
    normalized_expected = deepcopy(expected)
    errors: list[str] = []
    for pointer, operations in rules.items():
        try:
            actual_value = _value_at_pointer(normalized_actual, pointer)
            expected_value = _value_at_pointer(normalized_expected, pointer)
            if not isinstance(actual_value, str):
                raise ArgumentNormalizationError(
                    f"JSON Pointer '{pointer}' must target an actual string value."
                )
            if not isinstance(expected_value, str):
                raise ArgumentNormalizationError(
                    f"JSON Pointer '{pointer}' must target an expected string value."
                )
            _replace_at_pointer(
                normalized_actual,
                pointer,
                _normalize_string(actual_value, operations),
            )
            _replace_at_pointer(
                normalized_expected,
                pointer,
                _normalize_string(expected_value, operations),
            )
        except (ArgumentNormalizationError, KeyError, IndexError, TypeError) as exc:
            errors.append(str(exc))
    return normalized_actual, normalized_expected, errors
