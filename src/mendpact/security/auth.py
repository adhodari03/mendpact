"""Environment-only authentication for remote MCP targets."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BEARER_TOKEN = re.compile(r"^[A-Za-z0-9._~+/\-]+=*$")
_MAX_TOKEN_LENGTH = 8192


class AuthenticationConfigurationError(ValueError):
    """Raised when target authentication cannot be configured safely."""


@dataclass(frozen=True)
class BearerAuthentication:
    """Bearer credential loaded from an environment variable."""

    environment_variable: str
    token: str = field(repr=False, compare=False)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def load_bearer_authentication(
    environment_variable: str | None,
    *,
    environment: Mapping[str, str] | None = None,
) -> BearerAuthentication | None:
    """Resolve an environment-variable reference without accepting inline secrets."""

    if environment_variable is None:
        return None
    if not _ENVIRONMENT_NAME.fullmatch(environment_variable):
        raise AuthenticationConfigurationError(
            "Bearer token environment variable must be a valid environment name."
        )

    values = environment if environment is not None else os.environ
    token = values.get(environment_variable)
    if token is None:
        raise AuthenticationConfigurationError(
            f"Bearer token environment variable is not set: {environment_variable}"
        )
    if not token:
        raise AuthenticationConfigurationError(
            f"Bearer token environment variable is empty: {environment_variable}"
        )
    if len(token) > _MAX_TOKEN_LENGTH:
        raise AuthenticationConfigurationError(
            f"Bearer token in {environment_variable} exceeds {_MAX_TOKEN_LENGTH} characters."
        )
    if not _BEARER_TOKEN.fullmatch(token):
        raise AuthenticationConfigurationError(
            f"Bearer token in {environment_variable} contains characters not allowed by RFC 6750."
        )
    return BearerAuthentication(environment_variable=environment_variable, token=token)


def redact_authentication(
    value: object,
    authentication: BearerAuthentication | None,
) -> str:
    """Render an error boundary while removing the configured credential."""

    rendered = str(value)
    if authentication is not None and authentication.token:
        rendered = rendered.replace(authentication.token, "[REDACTED]")
    return rendered
