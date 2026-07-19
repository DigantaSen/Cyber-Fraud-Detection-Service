"""
Integration tests for Auth endpoints.
DB and Redis are mocked — no real connections needed.
"""
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


class TestRegister:

    @pytest.mark.asyncio
    async def test_register_success(self, async_client, mock_user, mock_db, mock_redis):
        """POST /register creates user and returns 201."""
        with (
            patch("routers.auth_router.get_db", return_value=mock_db),
            patch("routers.auth_router.get_redis", return_value=mock_redis),
            patch("services.auth_service.UserRepository") as mock_user_repo_cls,
            patch("services.auth_service.IdempotencyRepository") as mock_idem_repo_cls,
        ):
            mock_user_repo = AsyncMock()
            mock_user_repo.get_by_email.return_value = None  # No existing user
            mock_user_repo.create.return_value = mock_user
            mock_user_repo_cls.return_value = mock_user_repo

            mock_idem_repo = AsyncMock()
            mock_idem_repo.get.return_value = None  # No cached response
            mock_idem_repo_cls.return_value = mock_idem_repo

            response = await async_client.post(
                "/api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "password": "Password1",
                    "phone": "+919876543210",
                    "role": "CITIZEN",
                },
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "success"
        assert "userId" in body["data"] or "user_id" in body["data"]

    @pytest.mark.asyncio
    async def test_register_missing_idempotency_key(self, async_client):
        """POST /register without Idempotency-Key returns error."""
        response = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "x@x.com", "password": "Password1", "phone": "+911234567890", "role": "CITIZEN"},
        )
        # Should return 4xx (missing idempotency key)
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_register_invalid_role(self, async_client):
        """POST /register with invalid role returns 422."""
        response = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "x@x.com", "password": "Password1", "phone": "+911234567890", "role": "HACKER"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, async_client, mock_db, mock_redis):
        """POST /register with existing email returns 409."""
        with (
            patch("routers.auth_router.get_db", return_value=mock_db),
            patch("routers.auth_router.get_redis", return_value=mock_redis),
            patch("services.auth_service.UserRepository") as mock_user_repo_cls,
            patch("services.auth_service.IdempotencyRepository") as mock_idem_repo_cls,
        ):
            mock_user_repo = AsyncMock()
            mock_user_repo.get_by_email.return_value = MagicMock()  # User exists
            mock_user_repo_cls.return_value = mock_user_repo

            mock_idem_repo = AsyncMock()
            mock_idem_repo.get.return_value = None  # No cached response
            mock_idem_repo_cls.return_value = mock_idem_repo

            response = await async_client.post(
                "/api/v1/auth/register",
                json={
                    "email": "existing@example.com",
                    "password": "Password1",
                    "phone": "+919876543210",
                    "role": "CITIZEN",
                },
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["errorCode"] == "DUPLICATE_EMAIL"


class TestLogin:

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, async_client, mock_db, mock_redis):
        """POST /login with wrong password returns 401."""
        with (
            patch("routers.auth_router.get_db", return_value=mock_db),
            patch("routers.auth_router.get_redis", return_value=mock_redis),
            patch("services.auth_service.UserRepository") as mock_user_repo_cls,
        ):
            mock_user_repo = AsyncMock()
            mock_user_repo.get_by_email.return_value = None  # User not found
            mock_user_repo_cls.return_value = mock_user_repo

            response = await async_client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "WrongPass1"},
            )
        assert response.status_code == 401
        assert response.json()["detail"]["errorCode"] == "INVALID_CREDENTIALS"

    @pytest.mark.asyncio
    async def test_login_locked_account(self, async_client, mock_db, mock_redis):
        """POST /login returns 429 when account is soft-locked in Redis."""
        mock_redis.exists.return_value = 1  # Account is locked

        with (
            patch("routers.auth_router.get_db", return_value=mock_db),
            patch("routers.auth_router.get_redis", return_value=mock_redis),
        ):
            response = await async_client.post(
                "/api/v1/auth/login",
                json={"email": "locked@example.com", "password": "Password1"},
            )
        assert response.status_code == 429
        assert response.json()["detail"]["errorCode"] == "ACCOUNT_LOCKED"


class TestMe:

    @pytest.mark.asyncio
    async def test_me_success(self, async_client, mock_user):
        """GET /me returns user profile from JWT including orgId and jurisdictionId."""
        from security.jwt import sign_access_token
        from main import app
        
        mock_user.org_id = uuid.uuid4()
        mock_user.jurisdiction_id = "JUR_TEST_01"
        token = sign_access_token(mock_user)
        
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = 0
        app.state.redis = mock_redis
        
        response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["userId"] == str(mock_user.user_id)
        assert body["data"]["orgId"] == str(mock_user.org_id)
        assert body["data"]["jurisdictionId"] == "JUR_TEST_01"


class TestHealthEndpoints:

    @pytest.mark.asyncio
    async def test_liveness(self, async_client):
        """GET /health/live always returns 200."""
        response = await async_client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"
