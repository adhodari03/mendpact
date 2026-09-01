"""Read-only OAuth metadata inspection for authenticated MCP targets."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx2

from mendpact.domain import (
    AuthorizationServerEvidence,
    Finding,
    OAuthMetadataEvidence,
    OAuthMetadataStatus,
    Severity,
)
from mendpact.security.targets import TargetPolicy, UnsafeTargetError, validate_target_url

_RESOURCE_METADATA = re.compile(r'resource_metadata\s*=\s*"([^"\\]*)"', re.IGNORECASE)
_CHALLENGE_SCOPE = re.compile(r'scope\s*=\s*"([^"\\]*)"', re.IGNORECASE)
_MAX_METADATA_BYTES = 1_000_000


def _finding(
    rule_id: str,
    severity: Severity,
    title: str,
    message: str,
    *,
    subject: str,
    evidence: dict[str, Any] | None = None,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        title=title,
        message=message,
        subject=subject,
        evidence=evidence or {},
    )


def _origin(parts: SplitResult) -> str:
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _protected_resource_candidates(target: str) -> list[str]:
    parts = urlsplit(target)
    root = f"{_origin(parts)}/.well-known/oauth-protected-resource"
    path = parts.path.lstrip("/")
    candidates = [f"{root}/{path}"] if path else []
    candidates.append(root)
    return list(dict.fromkeys(candidates))


def _authorization_server_candidates(issuer: str) -> list[str]:
    parts = urlsplit(issuer)
    origin = _origin(parts)
    path = parts.path.strip("/")
    if not path:
        return [
            f"{origin}/.well-known/oauth-authorization-server",
            f"{origin}/.well-known/openid-configuration",
        ]
    return [
        f"{origin}/.well-known/oauth-authorization-server/{path}",
        f"{origin}/.well-known/openid-configuration/{path}",
        f"{origin}/{path}/.well-known/openid-configuration",
    ]


def _challenge_values(header: str | None) -> tuple[str | None, list[str]]:
    if header is None or "bearer" not in header.lower():
        return None, []
    metadata_match = _RESOURCE_METADATA.search(header)
    scope_match = _CHALLENGE_SCOPE.search(header)
    scopes = scope_match.group(1).split() if scope_match else []
    return metadata_match.group(1) if metadata_match else None, scopes


async def _safe_https_url(url: str, policy: TargetPolicy) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise UnsafeTargetError("OAuth metadata URLs and endpoints must use HTTPS")
    if not parts.hostname:
        raise UnsafeTargetError("OAuth metadata URL must include a hostname")
    if parts.username or parts.password:
        raise UnsafeTargetError("OAuth metadata URL must not embed credentials")
    if parts.fragment:
        raise UnsafeTargetError("OAuth metadata URL must not contain a fragment")
    await validate_target_url(
        url,
        TargetPolicy(allow_private=policy.allow_private, allow_insecure_http=False),
    )


async def _json_document(
    client: httpx2.AsyncClient,
    url: str,
    warnings: list[str],
) -> dict[str, Any] | None:
    try:
        async with client.stream(
            "GET",
            url,
            headers={"Accept": "application/json"},
        ) as response:
            if response.status_code in {404, 405}:
                return None
            if response.status_code != 200:
                warnings.append(
                    f"OAuth metadata at {url} returned HTTP {response.status_code}."
                )
                return None
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > _MAX_METADATA_BYTES:
                    warnings.append(
                        f"OAuth metadata at {url} exceeded {_MAX_METADATA_BYTES} bytes."
                    )
                    return None
    except Exception as exc:
        warnings.append(f"Could not request OAuth metadata at {url}: {type(exc).__name__}")
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        warnings.append(f"OAuth metadata at {url} was not valid JSON.")
        return None
    if not isinstance(payload, dict):
        warnings.append(f"OAuth metadata at {url} was not a JSON object.")
        return None
    return payload


async def _challenge_metadata(
    client: httpx2.AsyncClient,
    target: str,
    warnings: list[str],
) -> tuple[str | None, list[str]]:
    try:
        async with client.stream(
            "GET",
            target,
            headers={"Accept": "application/json, text/event-stream"},
        ) as response:
            return _challenge_values(response.headers.get("www-authenticate"))
    except Exception as exc:
        warnings.append(
            f"Could not inspect the unauthenticated OAuth challenge: {type(exc).__name__}."
        )
        return None, []


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


async def _inspect_authorization_server(
    client: httpx2.AsyncClient,
    issuer: str,
    policy: TargetPolicy,
    warnings: list[str],
) -> tuple[AuthorizationServerEvidence, list[Finding]]:
    evidence = AuthorizationServerEvidence(issuer=issuer)
    findings: list[Finding] = []
    try:
        await _safe_https_url(issuer, policy)
    except (UnsafeTargetError, ValueError) as exc:
        findings.append(
            _finding(
                "MP-AUTH-004",
                Severity.HIGH,
                "Unsafe authorization server issuer",
                str(exc),
                subject=f"oauth:issuer:{issuer}",
            )
        )
        return evidence, findings

    selected_url: str | None = None
    document: dict[str, Any] | None = None
    mismatched_issuers: list[str] = []
    for candidate in _authorization_server_candidates(issuer):
        payload = await _json_document(client, candidate, warnings)
        if payload is None:
            continue
        discovered_issuer = payload.get("issuer")
        if discovered_issuer != issuer:
            mismatched_issuers.append(str(discovered_issuer))
            continue
        selected_url = candidate
        document = payload
        break

    if document is None:
        findings.append(
            _finding(
                "MP-AUTH-005",
                Severity.HIGH,
                "Authorization server metadata unavailable",
                "No OAuth or OpenID metadata document with an exactly matching issuer was found.",
                subject=f"oauth:issuer:{issuer}",
                evidence={"mismatched_issuers": mismatched_issuers},
            )
        )
        return evidence, findings

    evidence.metadata_url = selected_url
    authorization_endpoint = document.get("authorization_endpoint")
    token_endpoint = document.get("token_endpoint")
    for field_name, value in (
        ("authorization_endpoint", authorization_endpoint),
        ("token_endpoint", token_endpoint),
    ):
        if not isinstance(value, str):
            findings.append(
                _finding(
                    "MP-AUTH-006",
                    Severity.HIGH,
                    "Required OAuth endpoint missing",
                    f"Authorization server metadata must contain {field_name}.",
                    subject=f"oauth:issuer:{issuer}",
                )
            )
            continue
        try:
            await _safe_https_url(value, policy)
        except (UnsafeTargetError, ValueError) as exc:
            findings.append(
                _finding(
                    "MP-AUTH-006",
                    Severity.HIGH,
                    "Unsafe OAuth endpoint",
                    f"{field_name}: {exc}",
                    subject=f"oauth:issuer:{issuer}",
                )
            )

    evidence.authorization_endpoint = (
        authorization_endpoint if isinstance(authorization_endpoint, str) else None
    )
    evidence.token_endpoint = token_endpoint if isinstance(token_endpoint, str) else None
    methods = _string_list(document.get("code_challenge_methods_supported")) or []
    evidence.code_challenge_methods_supported = methods
    evidence.client_id_metadata_document_supported = (
        document.get("client_id_metadata_document_supported") is True
    )
    if "S256" not in methods:
        findings.append(
            _finding(
                "MP-AUTH-007",
                Severity.MEDIUM,
                "PKCE S256 support was not advertised",
                "An MCP OAuth client must verify PKCE support before authorization.",
                subject=f"oauth:issuer:{issuer}",
            )
        )
    return evidence, findings


async def inspect_oauth_metadata(
    target: str,
    *,
    bearer_token_env: str | None = None,
    policy: TargetPolicy,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> tuple[OAuthMetadataEvidence, list[Finding]]:
    """Inspect protected-resource and authorization-server metadata without a token."""

    warnings: list[str] = []
    findings: list[Finding] = []
    timeout = httpx2.Timeout(10.0)
    async with httpx2.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        transport=transport,
    ) as client:
        challenge_url, challenge_scopes = await _challenge_metadata(
            client,
            target,
            warnings,
        )
        candidates = [challenge_url] if challenge_url else []
        candidates.extend(_protected_resource_candidates(target))
        candidates = list(dict.fromkeys(candidate for candidate in candidates if candidate))

        selected_url: str | None = None
        document: dict[str, Any] | None = None
        for candidate in candidates:
            try:
                await _safe_https_url(candidate, policy)
            except (UnsafeTargetError, ValueError) as exc:
                findings.append(
                    _finding(
                        "MP-AUTH-002",
                        Severity.HIGH,
                        "Unsafe protected-resource metadata URL",
                        str(exc),
                        subject="oauth:protected-resource",
                        evidence={"url": candidate},
                    )
                )
                continue
            payload = await _json_document(client, candidate, warnings)
            if payload is not None:
                selected_url = candidate
                document = payload
                break

        if document is None:
            findings.append(
                _finding(
                    "MP-AUTH-001",
                    Severity.HIGH,
                    "Protected-resource metadata not found",
                    (
                        "Bearer authentication is configured, but RFC 9728 metadata was not found."
                        if bearer_token_env is not None
                        else "RFC 9728 metadata was not found for the MCP target."
                    ),
                    subject="oauth:protected-resource",
                )
            )
            return (
                OAuthMetadataEvidence(
                    status=OAuthMetadataStatus.NOT_FOUND,
                    credential_source=(
                        "environment" if bearer_token_env is not None else "none"
                    ),
                    bearer_token_env=bearer_token_env,
                    challenge_metadata_url=challenge_url,
                    challenge_scopes=challenge_scopes,
                    warnings=warnings,
                ),
                findings,
            )

        resource = document.get("resource")
        authorization_servers = _string_list(document.get("authorization_servers"))
        scopes_supported = _string_list(document.get("scopes_supported")) or []
        if resource != target:
            findings.append(
                _finding(
                    "MP-AUTH-003",
                    Severity.HIGH,
                    "Protected resource identifier mismatch",
                    "The metadata resource must exactly match the scanned MCP target.",
                    subject="oauth:protected-resource",
                    evidence={"expected": target, "actual": resource},
                )
            )
        if not authorization_servers:
            findings.append(
                _finding(
                    "MP-AUTH-008",
                    Severity.HIGH,
                    "Authorization servers missing",
                    "Protected-resource metadata must list at least one authorization server.",
                    subject="oauth:protected-resource",
                )
            )
            authorization_servers = []

        server_evidence: list[AuthorizationServerEvidence] = []
        for issuer in authorization_servers:
            discovered, server_findings = await _inspect_authorization_server(
                client,
                issuer,
                policy,
                warnings,
            )
            server_evidence.append(discovered)
            findings.extend(server_findings)

    status = (
        OAuthMetadataStatus.INVALID
        if any(finding.severity.rank >= Severity.HIGH.rank for finding in findings)
        else OAuthMetadataStatus.VALID
    )
    return (
        OAuthMetadataEvidence(
            status=status,
            credential_source=(
                "environment" if bearer_token_env is not None else "none"
            ),
            bearer_token_env=bearer_token_env,
            challenge_metadata_url=challenge_url,
            challenge_scopes=challenge_scopes,
            protected_resource_metadata_url=selected_url,
            resource=resource if isinstance(resource, str) else None,
            authorization_servers=authorization_servers,
            scopes_supported=scopes_supported,
            server_metadata=server_evidence,
            warnings=warnings,
        ),
        findings,
    )
