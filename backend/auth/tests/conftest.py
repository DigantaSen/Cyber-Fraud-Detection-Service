"""Shared pytest fixtures for Auth Service tests."""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Generate dummy keys for JWT testing
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
).decode("utf-8")
_public_pem = _private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode("utf-8")

os.environ["JWT_PRIVATE_KEY"] = _private_pem
os.environ["JWT_PUBLIC_KEY"] = _public_pem

from config import settings
settings.JWT_PRIVATE_KEY = _private_pem
settings.JWT_PUBLIC_KEY = _public_pem

from main import app
from models.user import User
from security.password import hash_password


@pytest.fixture
def mock_user():
    """A fake User object for testing."""
    return User(
        user_id=uuid.uuid4(),
        email="test@example.com",
        password_hash=hash_password("Password1"),
        phone="+919876543210",
        role="CITIZEN",
        org_id=None,
        jurisdiction_id=None,
        mfa_enabled=False,
        mfa_secret_enc=None,
        status="ACTIVE",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        last_login_at=None,
    )


@pytest.fixture
def mock_db():
    """Mock async SQLAlchemy session."""
    session = MagicMock()
    # session.begin() returns an async context manager
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.begin.return_value = ctx
    return session


@pytest.fixture
def mock_redis():
    """Mock Redis async client."""
    redis = AsyncMock()
    redis.exists.return_value = 0   # Not locked by default
    redis.get.return_value = None
    redis.incr.return_value = 1
    return redis


@pytest.fixture
async def async_client(mock_db, mock_redis):
    """Async HTTP client for endpoint testing."""
    from db import get_db
    from redis_client import get_redis
    
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: mock_redis
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
        
    app.dependency_overrides.clear()
