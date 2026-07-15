"""Shared fixtures for Citizen BFF tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport, Response
from main import app


@pytest.fixture
def mock_case_client():
    client = AsyncMock()
    client.request = AsyncMock(return_value=Response(
        200,
        json={"status": "success", "data": {"caseId": "abc-123"}},
    ))
    return client


@pytest.fixture
def mock_bot_client():
    client = AsyncMock()
    client.request = AsyncMock(return_value=Response(
        200,
        json={"status": "success", "data": {"sessionId": "ses-456", "response": "Hello"}},
    ))
    return client


@pytest.fixture
def mock_evidence_client_offline():
    """Simulate Evidence Service being unreachable."""
    import httpx
    client = AsyncMock()
    client.request = AsyncMock(side_effect=httpx.RequestError("Connection refused"))
    return client


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def auth_headers():
    import uuid
    return {
        "Authorization": "Bearer test-token",
        "X-Correlation-ID": str(uuid.uuid4()),
    }
