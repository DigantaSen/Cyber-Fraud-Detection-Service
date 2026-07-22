import pytest
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get.return_value = None
    redis.setex.return_value = True
    redis.exists.return_value = 0
    # scan_iter: async generator that yields nothing
    async def empty_scan(*args, **kwargs):
        return
        yield  # make it an async generator
    redis.scan_iter = empty_scan
    return redis


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
