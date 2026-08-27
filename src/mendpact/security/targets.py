"""Validate remote targets before an MCP client connects to them."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import anyio


class UnsafeTargetError(ValueError):
    """Raised when a target violates MendPact's network policy."""


@dataclass(frozen=True)
class TargetPolicy:
    allow_private: bool = False
    allow_insecure_http: bool = False


def _is_disallowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _resolve(hostname: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for result in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM):
        addresses.add(ipaddress.ip_address(result[4][0]))
    return addresses


async def validate_target_url(url: str, policy: TargetPolicy) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeTargetError("MCP target must use http:// or https://")
    if not parsed.hostname:
        raise UnsafeTargetError("MCP target must include a hostname")
    if parsed.username or parsed.password:
        raise UnsafeTargetError("Credentials must not be embedded in the target URL")
    if parsed.scheme == "http" and not policy.allow_insecure_http:
        raise UnsafeTargetError(
            "Plain HTTP is blocked; use HTTPS or pass --allow-insecure-http for development"
        )

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await anyio.to_thread.run_sync(_resolve, parsed.hostname, port)
    except socket.gaierror as exc:
        raise UnsafeTargetError(f"Could not resolve target hostname: {parsed.hostname}") from exc

    if not addresses:
        raise UnsafeTargetError(f"Target hostname resolved to no addresses: {parsed.hostname}")
    if not policy.allow_private:
        blocked = sorted(str(address) for address in addresses if _is_disallowed(address))
        if blocked:
            raise UnsafeTargetError(
                "Target resolves to a private or special-use address: " + ", ".join(blocked)
            )
