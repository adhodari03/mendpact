from __future__ import annotations

import pytest

from mendpact.argument_matching import normalize_argument_documents
from mendpact.domain import ArgumentNormalizer, BehaviorExpectation


def test_normalizes_nested_array_and_escaped_object_paths() -> None:
    actual = {
        "items": [{"name": " API "}],
        "a/b": {"~label": " READY "},
    }
    expected = {
        "items": [{"name": "api"}],
        "a/b": {"~label": "READY"},
    }
    rules = {
        "/items/0/name": [ArgumentNormalizer.TRIM, ArgumentNormalizer.CASEFOLD],
        "/a~1b/~0label": [ArgumentNormalizer.TRIM],
    }

    normalized_actual, normalized_expected, errors = normalize_argument_documents(
        actual,
        expected,
        rules,
    )

    assert not errors
    assert normalized_actual == normalized_expected
    assert actual["items"][0]["name"] == " API "
    assert expected["items"][0]["name"] == "api"


@pytest.mark.parametrize(
    ("arguments", "rules", "message"),
    [
        (
            {"component": "api"},
            {"component": [ArgumentNormalizer.CASEFOLD]},
            "must start with '/'",
        ),
        (
            {"component": "api"},
            {"/missing": [ArgumentNormalizer.CASEFOLD]},
            "does not exist",
        ),
        (
            {"attempt": 1},
            {"/attempt": [ArgumentNormalizer.CASEFOLD]},
            "expected string value",
        ),
        (
            {"component": "api"},
            {"/component": []},
            "at least one normalizer",
        ),
        (
            {"component": "api"},
            {
                "/component": [
                    ArgumentNormalizer.CASEFOLD,
                    ArgumentNormalizer.CASEFOLD,
                ]
            },
            "duplicate normalizers",
        ),
        (
            {"component": "api"},
            {"/bad~path": [ArgumentNormalizer.CASEFOLD]},
            "invalid '~' escape",
        ),
    ],
)
def test_rejects_invalid_normalization_contracts(
    arguments: dict[str, object],
    rules: dict[str, list[ArgumentNormalizer]],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        BehaviorExpectation(
            tool="read_status",
            arguments=arguments,
            argument_normalization=rules,
        )


def test_unconfigured_values_are_not_normalized() -> None:
    actual = {"component": "API", "region": "US-EAST"}
    expected = {"component": "api", "region": "us-east"}

    normalized_actual, normalized_expected, errors = normalize_argument_documents(
        actual,
        expected,
        {"/component": [ArgumentNormalizer.CASEFOLD]},
    )

    assert not errors
    assert normalized_actual["component"] == normalized_expected["component"]
    assert normalized_actual["region"] != normalized_expected["region"]
