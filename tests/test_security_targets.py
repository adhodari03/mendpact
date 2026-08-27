import pytest

from mendpact.security.targets import TargetPolicy, UnsafeTargetError, validate_target_url


@pytest.mark.anyio
async def test_rejects_embedded_credentials() -> None:
    with pytest.raises(UnsafeTargetError, match="must not be embedded"):
        await validate_target_url(
            "https://user:secret@example.com/mcp",
            TargetPolicy(allow_private=True),
        )


@pytest.mark.anyio
async def test_rejects_plain_http_without_override() -> None:
    with pytest.raises(UnsafeTargetError, match="Plain HTTP"):
        await validate_target_url("http://127.0.0.1:8000/mcp", TargetPolicy())


@pytest.mark.anyio
async def test_allows_loopback_only_with_explicit_overrides() -> None:
    await validate_target_url(
        "http://127.0.0.1:8000/mcp",
        TargetPolicy(allow_private=True, allow_insecure_http=True),
    )
