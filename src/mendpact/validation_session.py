"""Guarded, bounded capture sessions for authorized real-world MCP validation."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import stat
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    model_validator,
)

from mendpact.contract_diff import validate_scan_contract
from mendpact.domain import PolicyProfile, PolicySnapshot, ScanReport, ScanStatus
from mendpact.evidence import write_new_evidence_file
from mendpact.policy import load_policy, target_policy
from mendpact.scanner import scan_mcp_url

MAX_VALIDATION_FILE_BYTES = 128 * 1024
MAX_APPROVAL_DAYS = 14
SESSION_MANIFEST_NAME = "session.json"
SESSION_NOTICE = (
    "Bounded metadata discovery from an explicitly approved local authorization record. "
    "No MCP tool or model provider was called. A passed policy is not a security certification. "
    "Target hashes are linkable fingerprints, not anonymization or signatures."
)
Scanner = Callable[..., Awaitable[ScanReport]]


class ValidationSessionError(ValueError):
    """Safe-to-display validation setup or session failure."""


class ValidationAuthorization(BaseModel):
    """Local authorization record that must be completed before any network operation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["mendpact.validation-authorization.v1"] = (
        "mendpact.validation-authorization.v1"
    )
    status: Literal["draft", "approved"] = "draft"
    target_alias: str = Field(default="", max_length=48)
    target_url: str = Field(default="", max_length=2048)
    target_kind: Literal["production_https", "isolated_loopback"] = "production_https"
    approved_by: str = Field(default="", max_length=120)
    permission_reference: str = Field(default="", max_length=500)
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    max_discovery_scans: int = Field(default=2, ge=1, le=2)
    stop_conditions_acknowledged: StrictBool = False
    allow_authenticated: StrictBool = False
    allow_tool_execution: StrictBool = False
    allow_provider_calls: StrictBool = False

    @model_validator(mode="after")
    def validate_approved_record(self) -> ValidationAuthorization:
        if self.status == "draft":
            return self
        if (
            re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", self.target_alias) is None
            or not self.target_url
        ):
            raise ValueError("approved authorization requires a target alias and URL")
        if not self.approved_by.strip() or len(self.permission_reference.strip()) < 10:
            raise ValueError("approved authorization requires reviewer and permission evidence")
        if self.approved_at is None or self.expires_at is None:
            raise ValueError("approved authorization requires approval and expiry times")
        if self.approved_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("authorization times must include a UTC offset")
        if self.expires_at <= self.approved_at:
            raise ValueError("authorization expiry must follow approval")
        if self.expires_at - self.approved_at > timedelta(days=MAX_APPROVAL_DAYS):
            raise ValueError("authorization cannot exceed 14 days")
        if not self.stop_conditions_acknowledged:
            raise ValueError("validation stop conditions must be acknowledged")
        if self.allow_authenticated or self.allow_tool_execution or self.allow_provider_calls:
            raise ValueError("guarded validation cannot authorize expanded operations")
        return self


class ValidationSessionScan(BaseModel):
    """Integrity and outcome record for one sequential discovery scan."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1, le=2)
    status: ScanStatus
    scan_id: str = Field(min_length=1)
    generated_at: datetime
    report_file: str = Field(pattern=r"^scan-0[12]\.json$")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ValidationSessionManifest(BaseModel):
    """Versioned local evidence for a bounded validation capture session."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["mendpact.validation-session.v1"] = (
        "mendpact.validation-session.v1"
    )
    generated_at: datetime
    status: ScanStatus
    target_alias: str = Field(min_length=1, max_length=48)
    target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_expires_at: datetime
    workspace_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    planned_scan_count: int = Field(ge=1, le=2)
    completed_scan_count: int = Field(ge=1, le=2)
    stopped_early: bool
    authenticated: Literal[False] = False
    tool_execution: Literal[False] = False
    provider_calls: Literal[False] = False
    scans: list[ValidationSessionScan] = Field(min_length=1, max_length=2)
    notice: str = SESSION_NOTICE

    @model_validator(mode="after")
    def validate_session_outcome(self) -> ValidationSessionManifest:
        if self.completed_scan_count != len(self.scans):
            raise ValueError("completed scan count does not match session scans")
        if [scan.index for scan in self.scans] != list(
            range(1, self.completed_scan_count + 1)
        ):
            raise ValueError("session scan indexes must be contiguous")
        expected_status = (
            ScanStatus.ERROR
            if any(scan.status == ScanStatus.ERROR for scan in self.scans)
            else ScanStatus.FAILED
            if any(scan.status == ScanStatus.FAILED for scan in self.scans)
            else ScanStatus.PASSED
        )
        if self.status != expected_status:
            raise ValueError("session status does not match scan outcomes")
        if self.stopped_early != (self.completed_scan_count < self.planned_scan_count):
            raise ValueError("stopped_early does not match the scan counts")
        if self.stopped_early and self.scans[-1].status != ScanStatus.ERROR:
            raise ValueError("only an operational scan error can stop a session early")
        return self


@dataclass(frozen=True)
class ValidationSessionPlan:
    workspace: Path
    authorization: ValidationAuthorization
    authorization_sha256: str
    workspace_manifest_sha256: str
    policy: PolicySnapshot


@dataclass(frozen=True)
class ValidationSessionResult:
    manifest: ValidationSessionManifest
    reports: list[ScanReport]


def _now() -> datetime:
    return datetime.now(UTC)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationSessionError("Validation JSON contains duplicate keys.")
        result[key] = value
    return result


def _read_private_file(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_mode & 0o077
            ):
                raise ValidationSessionError(
                    "Validation inputs must be private regular files with permissions 0600."
                )
            raw = stream.read(MAX_VALIDATION_FILE_BYTES + 1)
        if len(raw) > MAX_VALIDATION_FILE_BYTES:
            raise ValidationSessionError("Validation input exceeds the 128 KiB limit.")
        return raw
    except ValidationSessionError:
        raise
    except OSError as exc:
        raise ValidationSessionError("Validation input cannot be read safely.") from exc


def _read_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = _read_private_file(path)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            raise ValueError
        return raw, value
    except ValidationSessionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationSessionError("Validation JSON is unreadable or invalid.") from exc


def _safe_workspace(path: Path) -> Path:
    absolute = path.absolute()
    try:
        if any(item.is_symlink() for item in (absolute, *absolute.parents)):
            raise ValidationSessionError("Validation workspace paths must not contain symlinks.")
        metadata = absolute.stat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077:
            raise ValidationSessionError(
                "Validation workspace must be a private directory with permissions 0700."
            )
        root = absolute.parents[2]
        if absolute.parent.name != "validation" or absolute.parent.parent.name != "reports":
            raise ValidationSessionError(
                "Use a workspace created under reports/validation by the preparation script."
            )
        if absolute != root / "reports" / "validation" / absolute.name:
            raise ValidationSessionError("Validation workspace location is invalid.")
        return absolute
    except ValidationSessionError:
        raise
    except (OSError, IndexError) as exc:
        raise ValidationSessionError("Validation workspace cannot be inspected safely.") from exc


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationSessionError("Validation checkout provenance cannot be verified.") from exc


def _validate_target(authorization: ValidationAuthorization) -> None:
    try:
        if any(character.isspace() for character in authorization.target_url):
            raise ValueError
        parts = urlsplit(authorization.target_url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError
        _ = parts.port
        if authorization.target_kind == "production_https":
            if parts.scheme != "https":
                raise ValueError
            return
        if parts.scheme not in {"http", "https"}:
            raise ValueError
        hostname = parts.hostname.rstrip(".").lower()
        if hostname == "localhost":
            return
        if not ipaddress.ip_address(hostname).is_loopback:
            raise ValueError
    except ValueError as exc:
        raise ValidationSessionError(
            "Approved target URL does not match its safe production or loopback profile."
        ) from exc


def _validate_workspace_manifest(
    manifest: dict[str, Any],
    *,
    root: Path,
    policy_name: str,
    policy_sha256: str,
    now: datetime,
) -> None:
    try:
        environment = manifest["environment"]
        boundaries = manifest["boundaries"]
        created_at = datetime.fromisoformat(manifest["created_at"])
        delete_by = datetime.fromisoformat(manifest["review_or_delete_by"])
        if (
            manifest["schema_version"] != "mendpact.validation-workspace.v1"
            or manifest["status"] != "not-run"
            or not isinstance(environment, dict)
            or not isinstance(boundaries, dict)
            or environment.get("working_tree_dirty") is not False
            or environment.get("revision") != _git(root, "rev-parse", "HEAD")
            or _git(root, "status", "--porcelain")
            or boundaries
            != {"provider_calls": False, "tool_execution": False, "publishing": False}
            or manifest["template_sha256"][policy_name] != policy_sha256
            or created_at.tzinfo is None
            or delete_by.tzinfo is None
            or delete_by <= now
            or delete_by - created_at > timedelta(days=MAX_APPROVAL_DAYS)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationSessionError(
            "Workspace provenance is stale, dirty, expired, or inconsistent; prepare a fresh one."
        ) from exc


def inspect_validation_session(
    workspace: Path,
    *,
    inspected_at: datetime | None = None,
) -> ValidationSessionPlan:
    """Validate local approval, policies, checkout identity, retention, and output freshness."""

    current = inspected_at or _now()
    directory = _safe_workspace(workspace)
    root = directory.parents[2]
    authorization_raw, authorization_value = _read_json(directory / "authorization.json")
    manifest_raw, manifest = _read_json(directory / "manifest.json")
    _read_private_file(directory / "review.md")
    try:
        authorization = ValidationAuthorization.model_validate(authorization_value)
    except ValidationError as exc:
        raise ValidationSessionError(
            "Authorization record is invalid; complete the generated template locally."
        ) from exc
    if authorization.status != "approved":
        raise ValidationSessionError(
            "Authorization remains draft; do not contact the target until it is approved."
        )
    if authorization.approved_at is None or authorization.expires_at is None:
        raise ValidationSessionError("Authorization record is incomplete.")
    if authorization.approved_at > current or authorization.expires_at <= current:
        raise ValidationSessionError("Authorization is not currently valid.")
    _validate_target(authorization)

    policy_name = (
        "production.toml"
        if authorization.target_kind == "production_https"
        else "local-strict.toml"
    )
    policy_path = directory / policy_name
    policy_raw = _read_private_file(policy_path)
    try:
        policy = load_policy(policy_path, today=current.date())
    except ValueError as exc:
        raise ValidationSessionError("Selected validation policy is invalid.") from exc
    if authorization.target_kind == "production_https":
        if (
            policy.profile != PolicyProfile.PRODUCTION
            or policy.allow_private
            or policy.allow_insecure_http
        ):
            raise ValidationSessionError("Production validation requires the strict HTTPS policy.")
    elif not policy.allow_private or not policy.allow_insecure_http:
        raise ValidationSessionError("Loopback validation requires the strict local policy.")
    if policy.bearer_token_env is not None:
        raise ValidationSessionError("Guarded validation does not accept credentials.")
    _validate_workspace_manifest(
        manifest,
        root=root,
        policy_name=policy_name,
        policy_sha256=sha256(policy_raw).hexdigest(),
        now=current,
    )
    delete_by = datetime.fromisoformat(manifest["review_or_delete_by"])
    if authorization.expires_at > delete_by:
        raise ValidationSessionError("Authorization cannot outlive the workspace retention date.")
    if (directory / SESSION_MANIFEST_NAME).exists() or list(directory.glob("scan-*.json")):
        raise ValidationSessionError(
            "Validation outputs already exist; prepare a fresh workspace instead of overwriting."
        )
    return ValidationSessionPlan(
        workspace=directory,
        authorization=authorization,
        authorization_sha256=sha256(authorization_raw).hexdigest(),
        workspace_manifest_sha256=sha256(manifest_raw).hexdigest(),
        policy=policy,
    )


async def run_validation_session(
    workspace: Path,
    *,
    scanner: Scanner | None = None,
    started_at: datetime | None = None,
) -> ValidationSessionResult:
    """Run one or two sequential metadata scans from an approved local record, without retries."""

    current = started_at or _now()
    plan = inspect_validation_session(workspace, inspected_at=current)
    execute_scan = scanner or scan_mcp_url
    reports: list[ScanReport] = []
    scans: list[ValidationSessionScan] = []
    for index in range(1, plan.authorization.max_discovery_scans + 1):
        report = await execute_scan(
            plan.authorization.target_url,
            failure_threshold=plan.policy.scan_fail_on,
            policy=target_policy(plan.policy),
            applied_policy=plan.policy,
            authentication=None,
        )
        if report.target != plan.authorization.target_url:
            raise ValidationSessionError("Scanner returned evidence for an unexpected target.")
        if report.status != ScanStatus.ERROR:
            graph = validate_scan_contract(report, "validation")
            if graph.target != plan.authorization.target_url:
                raise ValidationSessionError(
                    "Scanner returned a capability graph for an unexpected target."
                )
        report_file = f"scan-{index:02}.json"
        content = report.model_dump_json(indent=2)
        write_new_evidence_file(plan.workspace / report_file, content)
        reports.append(report)
        scans.append(
            ValidationSessionScan(
                index=index,
                status=report.status,
                scan_id=report.scan_id,
                generated_at=report.generated_at,
                report_file=report_file,
                report_sha256=sha256((content + "\n").encode()).hexdigest(),
            )
        )
        if report.status == ScanStatus.ERROR:
            break

    status = (
        ScanStatus.ERROR
        if any(scan.status == ScanStatus.ERROR for scan in scans)
        else ScanStatus.FAILED
        if any(scan.status == ScanStatus.FAILED for scan in scans)
        else ScanStatus.PASSED
    )
    if plan.authorization.expires_at is None:
        raise ValidationSessionError("Authorization record is incomplete.")
    manifest = ValidationSessionManifest(
        generated_at=current,
        status=status,
        target_alias=plan.authorization.target_alias,
        target_sha256=sha256(plan.authorization.target_url.encode()).hexdigest(),
        authorization_sha256=plan.authorization_sha256,
        authorization_expires_at=plan.authorization.expires_at,
        workspace_manifest_sha256=plan.workspace_manifest_sha256,
        policy_source_sha256=plan.policy.source_sha256,
        planned_scan_count=plan.authorization.max_discovery_scans,
        completed_scan_count=len(scans),
        stopped_early=len(scans) < plan.authorization.max_discovery_scans,
        scans=scans,
    )
    write_new_evidence_file(
        plan.workspace / SESSION_MANIFEST_NAME,
        manifest.model_dump_json(indent=2),
    )
    return ValidationSessionResult(manifest=manifest, reports=reports)
