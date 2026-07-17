"""Tests for Citizen BFF proxy behavior."""
import uuid
from unittest.mock import AsyncMock
from httpx import Response

import pytest


class TestReportProxy:

    @pytest.mark.asyncio
    async def test_report_proxied_to_case_service(self, async_client, mock_case_client, auth_headers):
        """POST /citizen/report should proxy to Case Service."""
        from main import app
        from security.jwt import get_current_user, get_optional_user
        from clients.case_client import get_case_client
        
        user_mock = AsyncMock()
        user_mock.user_id = uuid.uuid4()
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_optional_user] = lambda: user_mock
        app.dependency_overrides[get_case_client] = lambda: mock_case_client
        
        try:
            response = await async_client.post(
                "/api/v1/citizen/report",
                json={"title": "Test", "description": "Fraud", "complaint_type": "UPI_FRAUD", "language_code": "en"},
                headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
            )
            assert response.status_code in (200, 201)
            # Case client was called
            mock_case_client.request.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_correlation_id_forwarded(self, async_client, mock_case_client, auth_headers):
        """X-Correlation-ID should be forwarded in the downstream call."""
        from main import app
        from security.jwt import get_current_user
        from clients.case_client import get_case_client
        
        corr_id = str(uuid.uuid4())
        auth_headers["X-Correlation-ID"] = corr_id

        user_mock = AsyncMock()
        user_mock.user_id = uuid.uuid4()
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_case_client] = lambda: mock_case_client
        
        try:
            await async_client.get(
                f"/api/v1/citizen/cases/{uuid.uuid4()}",
                headers=auth_headers,
            )
            # Verify X-Correlation-ID appears in the forwarded call headers
            call_kwargs = mock_case_client.request.call_args[1]
            forwarded_headers = call_kwargs.get("headers", {})
            assert forwarded_headers.get("X-Correlation-ID") == corr_id
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_user_context_forwarded(self, async_client, mock_case_client, auth_headers):
        """X-User-Context should be injected into downstream headers."""
        import json
        from main import app
        from security.jwt import get_current_user
        from clients.case_client import get_case_client
        
        user_mock = AsyncMock()
        user_mock.user_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_case_client] = lambda: mock_case_client
        
        try:
            await async_client.get(
                f"/api/v1/citizen/cases/{uuid.uuid4()}",
                headers=auth_headers,
            )
            call_kwargs = mock_case_client.request.call_args[1]
            forwarded_headers = call_kwargs.get("headers", {})
            assert "X-User-Context" in forwarded_headers
            context = json.loads(forwarded_headers["X-User-Context"])
            assert context["role"] == "CITIZEN"
            assert context["userId"] == "12345678-1234-5678-1234-567812345678"
        finally:
            app.dependency_overrides.clear()


class TestEvidenceServiceOffline:

    @pytest.mark.asyncio
    async def test_evidence_upload_returns_503_when_offline(
        self, async_client, mock_evidence_client_offline, auth_headers
    ):
        """POST /citizen/cases/:id/evidence → 503 when Evidence Service offline."""
        from main import app
        from security.jwt import get_current_user
        from clients.evidence_client import get_evidence_client
        
        user_mock = AsyncMock()
        user_mock.user_id = uuid.uuid4()
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_evidence_client] = lambda: mock_evidence_client_offline
        
        try:
            response = await async_client.post(
                f"/api/v1/citizen/cases/{uuid.uuid4()}/evidence",
                json={"filename": "screenshot.png"},
                headers=auth_headers,
            )
            assert response.status_code == 503
        finally:
            app.dependency_overrides.clear()


class TestBotProxy:

    @pytest.mark.asyncio
    async def test_bot_message_proxied(self, async_client, mock_bot_client, auth_headers):
        """POST /citizen/bot/message proxies to Bot Service."""
        from main import app
        from security.jwt import get_current_user
        from clients.bot_client import get_bot_client
        
        user_mock = AsyncMock()
        user_mock.user_id = uuid.uuid4()
        user_mock.role = "CITIZEN"
        user_mock.jti = "test"
        
        app.dependency_overrides[get_current_user] = lambda: user_mock
        app.dependency_overrides[get_bot_client] = lambda: mock_bot_client
        
        try:
            response = await async_client.post(
                "/api/v1/citizen/bot/message",
                json={"message": "I was scammed"},
                headers=auth_headers,
            )
            assert response.status_code == 200
            mock_bot_client.request.assert_called_once()
        finally:
            app.dependency_overrides.clear()


class TestHealthEndpoints:

    @pytest.mark.asyncio
    async def test_liveness(self, async_client):
        response = await async_client.get("/health/live")
        assert response.status_code == 200
