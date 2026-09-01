from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mendpact.authorization import audit_oauth_metadata
from mendpact.cli import app
from mendpact.domain import (
    AuthorizationAuditReport,
    ContractImpact,
    Finding,
    OAuthMetadataEvidence,
    OAuthMetadataStatus,
    PolicyProfile,
    PolicySnapshot,
    PolicyWaiver,
    ScanStatus,
    Severity,
    WaiverStatus,
)
from mendpact.security.targets import TargetPolicy, UnsafeTargetError

runner = CliRunner()
TARGET = "https://api.example.com/mcp"


@pytest.mark.anyio
async def test_audit_passes_valid_credential_free_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_validate(*args: object, **kwargs: object) -> None:
        return None

    async def fake_inspect(
        *args: object,
        **kwargs: object,
    ) -> tuple[OAuthMetadataEvidence, list[Finding]]:
        return (
            OAuthMetadataEvidence(
                status=OAuthMetadataStatus.VALID,
                resource=TARGET,
                authorization_servers=["https://auth.example.com"],
            ),
            [],
        )

    monkeypatch.setattr("mendpact.authorization.validate_target_url", fake_validate)
    monkeypatch.setattr("mendpact.authorization.inspect_oauth_metadata", fake_inspect)

    report = await audit_oauth_metadata(TARGET, policy=TargetPolicy())

    assert report.schema_version == "mendpact.authorization.v1"
    assert report.status == ScanStatus.PASSED
    assert report.metadata is not None
    assert report.metadata.credential_source == "none"
    assert report.metadata.bearer_token_env is None


@pytest.mark.anyio
async def test_audit_applies_configured_failure_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_validate(*args: object, **kwargs: object) -> None:
        return None

    async def fake_inspect(
        *args: object,
        **kwargs: object,
    ) -> tuple[OAuthMetadataEvidence, list[Finding]]:
        return (
            OAuthMetadataEvidence(status=OAuthMetadataStatus.VALID),
            [
                Finding(
                    rule_id="MP-AUTH-007",
                    severity=Severity.MEDIUM,
                    title="PKCE missing",
                    message="S256 was not advertised.",
                    subject="oauth:issuer:https://auth.example.com",
                )
            ],
        )

    monkeypatch.setattr("mendpact.authorization.validate_target_url", fake_validate)
    monkeypatch.setattr("mendpact.authorization.inspect_oauth_metadata", fake_inspect)

    default = await audit_oauth_metadata(TARGET, policy=TargetPolicy())
    strict = await audit_oauth_metadata(
        TARGET,
        failure_threshold=Severity.MEDIUM,
        policy=TargetPolicy(),
    )

    assert default.status == ScanStatus.PASSED
    assert strict.status == ScanStatus.FAILED


@pytest.mark.anyio
async def test_audit_reports_target_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_validate(*args: object, **kwargs: object) -> None:
        raise UnsafeTargetError("blocked target")

    monkeypatch.setattr("mendpact.authorization.validate_target_url", fake_validate)

    report = await audit_oauth_metadata(TARGET, policy=TargetPolicy())

    assert report.status == ScanStatus.ERROR
    assert report.metadata is None
    assert report.errors == ["UnsafeTargetError: blocked target"]


@pytest.mark.anyio
async def test_audit_applies_exact_active_policy_waiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_validate(*args: object, **kwargs: object) -> None:
        return None

    async def fake_inspect(
        *args: object,
        **kwargs: object,
    ) -> tuple[OAuthMetadataEvidence, list[Finding]]:
        return (
            OAuthMetadataEvidence(status=OAuthMetadataStatus.INVALID),
            [
                Finding(
                    rule_id="MP-AUTH-005",
                    severity=Severity.HIGH,
                    title="Metadata unavailable",
                    message="Issuer metadata could not be found.",
                    subject="oauth:issuer:https://auth.example.com",
                )
            ],
        )

    policy = PolicySnapshot(
        source_sha256="a" * 64,
        name="production",
        profile=PolicyProfile.PRODUCTION,
        scan_fail_on=Severity.HIGH,
        contract_fail_on=ContractImpact.RISKY,
        waivers=[
            PolicyWaiver(
                rule_id="MP-AUTH-005",
                subject="oauth:issuer:https://auth.example.com",
                reason="Temporary issuer rollout exception.",
                approved_by="security@example.com",
                approved_on=date(2026, 9, 1),
                expires_on=date(2026, 9, 8),
                status=WaiverStatus.ACTIVE,
            )
        ],
    )
    monkeypatch.setattr("mendpact.authorization.validate_target_url", fake_validate)
    monkeypatch.setattr("mendpact.authorization.inspect_oauth_metadata", fake_inspect)

    report = await audit_oauth_metadata(
        TARGET,
        policy=TargetPolicy(),
        applied_policy=policy,
    )

    assert report.status == ScanStatus.PASSED
    assert report.findings[0].waiver is not None
    assert report.findings[0].waiver.approved_by == "security@example.com"


def test_auth_check_cli_writes_versioned_report_without_a_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_audit(*args: object, **kwargs: object) -> AuthorizationAuditReport:
        return AuthorizationAuditReport(
            target=TARGET,
            status=ScanStatus.PASSED,
            failure_threshold=Severity.HIGH,
            metadata=OAuthMetadataEvidence(
                status=OAuthMetadataStatus.VALID,
                resource=TARGET,
                authorization_servers=["https://auth.example.com"],
            ),
        )

    monkeypatch.setattr("mendpact.cli.audit_oauth_metadata", fake_audit)
    output = tmp_path / "authorization.json"

    result = runner.invoke(
        app,
        ["auth-check", TARGET, "--output", str(output)],
    )

    assert result.exit_code == 0
    assert "authorization audit: PASSED" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "mendpact.authorization.v1"
    assert payload["metadata"]["credential_source"] == "none"
    assert payload["metadata"]["bearer_token_env"] is None
    assert "secret-value" not in output.read_text(encoding="utf-8")


def test_auth_check_policy_can_name_an_unset_token_without_loading_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_path = tmp_path / "mendpact.toml"
    policy_path.write_text(
        "\n".join(
            [
                'schema_version = "mendpact.policy.v1"',
                'name = "production"',
                'profile = "production"',
                'bearer_token_env = "MENDPACT_ACCESS_TOKEN"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("MENDPACT_ACCESS_TOKEN", raising=False)
    observed: dict[str, object] = {}

    async def fake_audit(*args: object, **kwargs: object) -> AuthorizationAuditReport:
        observed.update(kwargs)
        return AuthorizationAuditReport(
            target=TARGET,
            status=ScanStatus.PASSED,
            failure_threshold=Severity.HIGH,
            metadata=OAuthMetadataEvidence(status=OAuthMetadataStatus.VALID),
        )

    monkeypatch.setattr("mendpact.cli.audit_oauth_metadata", fake_audit)

    result = runner.invoke(app, ["auth-check", TARGET, "--policy", str(policy_path)])

    assert result.exit_code == 0
    applied_policy = observed["applied_policy"]
    assert isinstance(applied_policy, PolicySnapshot)
    assert applied_policy.bearer_token_env == "MENDPACT_ACCESS_TOKEN"
    assert "bearer_token_env" not in observed


def test_auth_check_rejects_policy_owned_threshold_override(tmp_path: Path) -> None:
    policy_path = tmp_path / "mendpact.toml"
    policy_path.write_text(
        "\n".join(
            [
                'schema_version = "mendpact.policy.v1"',
                'name = "production"',
                'profile = "production"',
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "auth-check",
            TARGET,
            "--policy",
            str(policy_path),
            "--fail-on",
            "medium",
        ],
    )

    assert result.exit_code == 2
    assert "policy-controlled options: --fail-on" in result.stdout
