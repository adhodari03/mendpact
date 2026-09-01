from __future__ import annotations

import json

import httpx2
import pytest

from mendpact.domain import OAuthMetadataStatus, Severity
from mendpact.security.oauth_metadata import inspect_oauth_metadata
from mendpact.security.targets import TargetPolicy

TARGET = "https://api.example.com/public/mcp"
RESOURCE_METADATA = "https://api.example.com/oauth/resource-metadata"
ISSUER = "https://auth.example.com/tenant"


async def _skip_dns_validation(*args: object, **kwargs: object) -> None:
    return None


def _authorization_server_metadata() -> dict[str, object]:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": "https://auth.example.com/tenant/authorize",
        "token_endpoint": "https://auth.example.com/tenant/token",
        "code_challenge_methods_supported": ["S256"],
        "client_id_metadata_document_supported": True,
    }


@pytest.mark.anyio
async def test_uses_bearer_challenge_and_validates_oauth_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert "authorization" not in request.headers
        if str(request.url) == TARGET:
            return httpx2.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        f'Bearer resource_metadata="{RESOURCE_METADATA}", '
                        'scope="tools:read profile"'
                    )
                },
            )
        if str(request.url) == RESOURCE_METADATA:
            return httpx2.Response(
                200,
                json={
                    "resource": TARGET,
                    "authorization_servers": [ISSUER],
                    "scopes_supported": ["tools:read"],
                },
            )
        if str(request.url) == (
            "https://auth.example.com/.well-known/oauth-authorization-server/tenant"
        ):
            return httpx2.Response(200, json=_authorization_server_metadata())
        return httpx2.Response(404)

    monkeypatch.setattr(
        "mendpact.security.oauth_metadata.validate_target_url",
        _skip_dns_validation,
    )
    evidence, findings = await inspect_oauth_metadata(
        TARGET,
        bearer_token_env="MENDPACT_ACCESS_TOKEN",
        policy=TargetPolicy(),
        transport=httpx2.MockTransport(handler),
    )

    assert evidence.status == OAuthMetadataStatus.VALID
    assert evidence.challenge_metadata_url == RESOURCE_METADATA
    assert evidence.challenge_scopes == ["tools:read", "profile"]
    assert evidence.authorization_servers == [ISSUER]
    assert evidence.server_metadata[0].client_id_metadata_document_supported is True
    assert findings == []
    assert requests


@pytest.mark.anyio
async def test_falls_back_to_path_then_root_well_known_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        requested.append(url)
        if url == TARGET:
            return httpx2.Response(405)
        if url.endswith("/.well-known/oauth-protected-resource/public/mcp"):
            return httpx2.Response(404)
        if url == "https://api.example.com/.well-known/oauth-protected-resource":
            return httpx2.Response(
                200,
                json={"resource": TARGET, "authorization_servers": [ISSUER]},
            )
        if url == "https://auth.example.com/.well-known/oauth-authorization-server/tenant":
            return httpx2.Response(200, json=_authorization_server_metadata())
        return httpx2.Response(404)

    monkeypatch.setattr(
        "mendpact.security.oauth_metadata.validate_target_url",
        _skip_dns_validation,
    )
    evidence, findings = await inspect_oauth_metadata(
        TARGET,
        bearer_token_env="MENDPACT_ACCESS_TOKEN",
        policy=TargetPolicy(),
        transport=httpx2.MockTransport(handler),
    )

    assert evidence.status == OAuthMetadataStatus.VALID
    assert evidence.protected_resource_metadata_url == (
        "https://api.example.com/.well-known/oauth-protected-resource"
    )
    assert requested.index(
        "https://api.example.com/.well-known/oauth-protected-resource/public/mcp"
    ) < requested.index("https://api.example.com/.well-known/oauth-protected-resource")
    assert findings == []


@pytest.mark.anyio
async def test_missing_protected_resource_metadata_is_high_severity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mendpact.security.oauth_metadata.validate_target_url",
        _skip_dns_validation,
    )
    evidence, findings = await inspect_oauth_metadata(
        TARGET,
        bearer_token_env="MENDPACT_ACCESS_TOKEN",
        policy=TargetPolicy(),
        transport=httpx2.MockTransport(lambda request: httpx2.Response(404)),
    )

    assert evidence.status == OAuthMetadataStatus.NOT_FOUND
    assert [finding.rule_id for finding in findings] == ["MP-AUTH-001"]
    assert findings[0].severity == Severity.HIGH


@pytest.mark.anyio
async def test_rejects_resource_and_issuer_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url == TARGET:
            return httpx2.Response(405)
        if url.endswith("/.well-known/oauth-protected-resource/public/mcp"):
            return httpx2.Response(
                200,
                json={
                    "resource": "https://different.example.com/mcp",
                    "authorization_servers": [ISSUER],
                },
            )
        if "auth.example.com" in url:
            metadata = _authorization_server_metadata()
            metadata["issuer"] = "https://attacker.example.com"
            return httpx2.Response(200, json=metadata)
        return httpx2.Response(404)

    monkeypatch.setattr(
        "mendpact.security.oauth_metadata.validate_target_url",
        _skip_dns_validation,
    )
    evidence, findings = await inspect_oauth_metadata(
        TARGET,
        bearer_token_env="MENDPACT_ACCESS_TOKEN",
        policy=TargetPolicy(),
        transport=httpx2.MockTransport(handler),
    )

    assert evidence.status == OAuthMetadataStatus.INVALID
    assert {finding.rule_id for finding in findings} == {
        "MP-AUTH-003",
        "MP-AUTH-005",
    }
    serialized = json.dumps([finding.model_dump(mode="json") for finding in findings])
    assert "MENDPACT_ACCESS_TOKEN" not in serialized


@pytest.mark.anyio
async def test_reports_missing_pkce_s256_as_medium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url == TARGET:
            return httpx2.Response(405)
        if url.endswith("/.well-known/oauth-protected-resource/public/mcp"):
            return httpx2.Response(
                200,
                json={"resource": TARGET, "authorization_servers": [ISSUER]},
            )
        if "oauth-authorization-server" in url:
            metadata = _authorization_server_metadata()
            metadata["code_challenge_methods_supported"] = ["plain"]
            return httpx2.Response(200, json=metadata)
        return httpx2.Response(404)

    monkeypatch.setattr(
        "mendpact.security.oauth_metadata.validate_target_url",
        _skip_dns_validation,
    )
    evidence, findings = await inspect_oauth_metadata(
        TARGET,
        bearer_token_env="MENDPACT_ACCESS_TOKEN",
        policy=TargetPolicy(),
        transport=httpx2.MockTransport(handler),
    )

    assert evidence.status == OAuthMetadataStatus.VALID
    assert [finding.rule_id for finding in findings] == ["MP-AUTH-007"]
    assert findings[0].severity == Severity.MEDIUM
