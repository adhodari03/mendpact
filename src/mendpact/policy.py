"""Versioned policy-as-code loading and production safety validation."""

from __future__ import annotations

import tomllib
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    model_validator,
)

from mendpact.domain import (
    ContractImpact,
    PolicyProfile,
    PolicySnapshot,
    Severity,
)
from mendpact.security.targets import TargetPolicy


class PolicyConfigurationError(ValueError):
    """Raised when a policy file is invalid or weakens its selected profile."""


class _PolicyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["mendpact.policy.v1"]
    name: str = Field(min_length=1, max_length=80)
    profile: PolicyProfile
    scan_fail_on: Severity | None = None
    contract_fail_on: ContractImpact | None = None
    allow_private: StrictBool | None = None
    allow_insecure_http: StrictBool | None = None

    @model_validator(mode="after")
    def validate_production_boundaries(self) -> _PolicyDocument:
        if self.profile != PolicyProfile.PRODUCTION:
            return self
        if self.allow_private:
            raise ValueError("production policies cannot allow private targets")
        if self.allow_insecure_http:
            raise ValueError("production policies cannot allow insecure HTTP")
        if self.scan_fail_on is not None and self.scan_fail_on.rank > Severity.HIGH.rank:
            raise ValueError("production scan_fail_on cannot be weaker than high")
        if (
            self.contract_fail_on is not None
            and self.contract_fail_on.rank > ContractImpact.RISKY.rank
        ):
            raise ValueError("production contract_fail_on cannot be weaker than risky")
        return self


def _resolved(document: _PolicyDocument, *, source_sha256: str) -> PolicySnapshot:
    default_contract_threshold = (
        ContractImpact.RISKY
        if document.profile == PolicyProfile.PRODUCTION
        else ContractImpact.BREAKING
    )
    return PolicySnapshot(
        source_sha256=source_sha256,
        name=document.name,
        profile=document.profile,
        scan_fail_on=document.scan_fail_on or Severity.HIGH,
        contract_fail_on=document.contract_fail_on or default_contract_threshold,
        allow_private=(
            document.allow_private if document.allow_private is not None else False
        ),
        allow_insecure_http=(
            document.allow_insecure_http
            if document.allow_insecure_http is not None
            else False
        ),
    )


def load_policy(path: Path) -> PolicySnapshot:
    """Load, validate, and resolve a MendPact TOML policy."""
    try:
        source = path.read_text(encoding="utf-8")
        payload: dict[str, Any] = tomllib.loads(source)
        document = _PolicyDocument.model_validate(payload)
    except OSError as exc:
        raise PolicyConfigurationError(f"could not read policy: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PolicyConfigurationError(f"invalid TOML: {exc}") from exc
    except ValidationError as exc:
        errors = "; ".join(error["msg"] for error in exc.errors())
        raise PolicyConfigurationError(errors) from exc
    return _resolved(document, source_sha256=sha256(source.encode("utf-8")).hexdigest())


def target_policy(snapshot: PolicySnapshot) -> TargetPolicy:
    """Translate a resolved product policy into the network validation boundary."""
    return TargetPolicy(
        allow_private=snapshot.allow_private,
        allow_insecure_http=snapshot.allow_insecure_http,
    )
