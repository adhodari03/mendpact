from __future__ import annotations

from pathlib import Path

import pytest

from mendpact.domain import ContractImpact, PolicyProfile, Severity
from mendpact.policy import PolicyConfigurationError, load_policy, target_policy


def _write_policy(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "mendpact.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_production_profile_resolves_strict_defaults(tmp_path: Path) -> None:
    path = _write_policy(
        tmp_path,
        '\n'.join(
            [
                'schema_version = "mendpact.policy.v1"',
                'name = "production"',
                'profile = "production"',
            ]
        ),
    )

    policy = load_policy(path)

    assert policy.profile == PolicyProfile.PRODUCTION
    assert len(policy.source_sha256) == 64
    assert policy.scan_fail_on == Severity.HIGH
    assert policy.contract_fail_on == ContractImpact.RISKY
    assert policy.allow_private is False
    assert policy.allow_insecure_http is False


def test_local_profile_requires_explicit_target_allowances(tmp_path: Path) -> None:
    default_path = _write_policy(
        tmp_path,
        '\n'.join(
            [
                'schema_version = "mendpact.policy.v1"',
                'name = "local"',
                'profile = "local"',
            ]
        ),
    )
    default = load_policy(default_path)
    assert default.allow_private is False
    assert default.allow_insecure_http is False

    explicit_path = tmp_path / "local-explicit.toml"
    explicit_path.write_text(
        default_path.read_text(encoding="utf-8")
        + '\nallow_private = true\nallow_insecure_http = true\n',
        encoding="utf-8",
    )
    explicit = load_policy(explicit_path)

    assert explicit.profile == PolicyProfile.LOCAL
    assert explicit.allow_private is True
    assert explicit.allow_insecure_http is True
    assert target_policy(explicit).allow_private is True


@pytest.mark.parametrize(
    ("setting", "message"),
    [
        ("allow_private = true", "cannot allow private targets"),
        ("allow_insecure_http = true", "cannot allow insecure HTTP"),
        ('scan_fail_on = "critical"', "cannot be weaker than high"),
        ('contract_fail_on = "breaking"', "cannot be weaker than risky"),
    ],
)
def test_production_profile_rejects_weak_settings(
    tmp_path: Path,
    setting: str,
    message: str,
) -> None:
    path = _write_policy(
        tmp_path,
        '\n'.join(
            [
                'schema_version = "mendpact.policy.v1"',
                'name = "production"',
                'profile = "production"',
                setting,
            ]
        ),
    )

    with pytest.raises(PolicyConfigurationError, match=message):
        load_policy(path)


def test_rejects_unknown_policy_fields(tmp_path: Path) -> None:
    path = _write_policy(
        tmp_path,
        '\n'.join(
            [
                'schema_version = "mendpact.policy.v1"',
                'name = "production"',
                'profile = "production"',
                'ignore_failures = true',
            ]
        ),
    )

    with pytest.raises(PolicyConfigurationError, match="Extra inputs are not permitted"):
        load_policy(path)
