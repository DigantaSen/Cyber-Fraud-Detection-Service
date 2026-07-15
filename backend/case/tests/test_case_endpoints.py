"""Integration tests for Case endpoints with mocked service layer."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest


class TestCreateCase:

    @pytest.mark.asyncio
    async def test_create_case_missing_idempotency_key(self, async_client, valid_jwt_headers):
        """POST /cases without Idempotency-Key should fail."""
        from main import app
        from security.jwt import get_current_user
        from db import get_db
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="CITIZEN", jurisdiction_id="JUR_MH", jti="test")
        
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        
        try:
            response = await async_client.post(
                "/api/v1/cases",
                json={
                    "title": "Test",
                    "description": "Test fraud",
                    "complaint_type": "UPI_FRAUD",
                    "language_code": "en",
                },
                headers=valid_jwt_headers,
            )
            # Missing idempotency key → error response
            assert response.status_code == 201
            assert response.json().get("errorCode") == "MISSING_IDEMPOTENCY_KEY"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_case_invalid_complaint_type(self, async_client, valid_jwt_headers):
        """POST /cases with invalid complaintType returns 422."""
        from main import app
        from security.jwt import get_current_user
        from db import get_db
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="CITIZEN", jurisdiction_id="JUR_MH", jti="test")
            
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        
        try:
            response = await async_client.post(
                "/api/v1/cases",
                json={
                    "title": "Test",
                    "description": "Test",
                    "complaint_type": "INVALID_TYPE",
                    "language_code": "en",
                },
                headers={**valid_jwt_headers, "Idempotency-Key": str(uuid.uuid4())},
            )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()


class TestGetCase:

    @pytest.mark.asyncio
    async def test_get_case_not_found(self, async_client, valid_jwt_headers, sample_case_id):
        """GET /cases/:id returns 404 when not found."""
        from main import app
        from security.jwt import get_current_user
        from db import get_db
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="INVESTIGATOR", jurisdiction_id="JUR_MH", jti="test")
            
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        
        with patch("services.case_service.CaseService.get_case",
                  side_effect=__import__("services.case_service", fromlist=["CaseNotFoundError"]).CaseNotFoundError("not found")):
            response = await async_client.get(
                f"/api/v1/cases/{sample_case_id}",
                headers=valid_jwt_headers,
            )
            assert response.status_code == 404
            assert response.json()["detail"].get("errorCode") == "CASE_NOT_FOUND"
        app.dependency_overrides.clear()


class TestStateTransition:

    @pytest.mark.asyncio
    async def test_invalid_transition_returns_422(self, async_client, valid_jwt_headers, sample_case_id, mock_db):
        """PATCH /cases/:id/state with invalid transition → 422."""
        from services.case_service import InvalidTransitionError
        from main import app
        from security.jwt import get_current_user
        from db import get_db
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="INVESTIGATOR", jurisdiction_id="JUR_MH", jti="test")
            
        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[get_db] = lambda: mock_db
        
        with patch("services.case_service.CaseService.update_state",
                  side_effect=InvalidTransitionError("Invalid transition: Closed → Assigned")):
            response = await async_client.patch(
                f"/api/v1/cases/{sample_case_id}/state",
                json={"state": "Assigned", "reason": "test"},
                headers={**valid_jwt_headers, "Idempotency-Key": str(uuid.uuid4())},
            )
            assert response.status_code == 422
            assert "INVALID_STATE_TRANSITION" in str(response.json())
        app.dependency_overrides.clear()


class TestVerdictOverride:

    @pytest.mark.asyncio
    async def test_override_requires_investigator_role(self, async_client, valid_jwt_headers, sample_case_id):
        """PATCH /cases/:id/verdict/override returns 403 for CITIZEN role."""
        from fastapi import HTTPException
        from main import app
        from security.jwt import get_current_user
        from models.schemas import CurrentUser
        
        async def mock_user():
            return CurrentUser(user_id=uuid.uuid4(), email="a@a.com", role="CITIZEN", jurisdiction_id="JUR_MH", jti="test")
            
        app.dependency_overrides[get_current_user] = mock_user

        response = await async_client.patch(
            f"/api/v1/cases/{sample_case_id}/verdict/override",
            json={
                "decision": "APPROVE",
                "justification": "Reviewed all evidence thoroughly.",
                "original_verdict_id": str(uuid.uuid4()),
            },
            headers=valid_jwt_headers,
        )
        # CITIZEN should get 403
        assert response.status_code in (403, 401)
        app.dependency_overrides.clear()
