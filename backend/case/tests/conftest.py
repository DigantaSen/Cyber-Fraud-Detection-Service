"""Shared fixtures for Case Service tests."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.begin.return_value.__aenter__ = AsyncMock(return_value=session)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture
def sample_case_id():
    return uuid.uuid4()


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def valid_jwt_headers():
    """Headers with a fake JWT for testing (Kong validates in production)."""
    # In tests: mock get_current_user to bypass JWT validation
    return {"Authorization": "Bearer fake-token", "X-Correlation-ID": str(uuid.uuid4())}
