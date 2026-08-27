"""Shared test configuration."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Keep the async integration suite on the installed asyncio backend."""

    return "asyncio"
