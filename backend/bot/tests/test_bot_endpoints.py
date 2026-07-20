"""Tests for Bot Service endpoints."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from services.language_service import detect_language, is_supported_language
from services.session_service import SessionService


# ── Language Detection Unit Tests ─────────────────────────────────────────────

class TestLanguageDetection:

    def test_detect_hindi(self):
        result = detect_language("मुझे एक अज्ञात कॉल आई और उन्होंने मेरे साथ धोखाधड़ी की")
        assert result == "hi"

    def test_detect_english(self):
        result = detect_language("I was defrauded by someone claiming to be from the bank")
        assert result == "en"

    def test_empty_string_returns_en(self):
        assert detect_language("") == "en"

    def test_short_string_returns_en(self):
        assert detect_language("hi") == "en"

    def test_unsupported_language_falls_back_to_en(self):
        # French text — not in supported list
        result = detect_language("Bonjour je suis très content de vous voir aujourd'hui")
        assert result in {"fr", "en"}  # May detect French, but service returns "en" for unsupported
        assert is_supported_language(result) or result == "en"

    def test_all_supported_langs_in_set(self):
        supported = {"hi", "bn", "te", "ta", "mr", "gu", "kn", "ml", "pa", "ur", "or", "as", "en"}
        for lang in supported:
            assert is_supported_language(lang)


# ── Session Service Unit Tests ─────────────────────────────────────────────────

class TestSessionService:

    @pytest.mark.asyncio
    async def test_create_session(self, mock_redis):
        svc = SessionService(mock_redis)
        result = await svc.create_session(
            lang_code="en",
            channel="WEB",
            user_id=None,
            first_message="I was scammed",
        )
        assert result["sessionId"] is not None
        assert result["turnCount"] == 1
        assert result["detectedLanguage"] == "en"
        assert len(result["messages"]) == 1
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, mock_redis):
        # scan_iter yields nothing → get_session returns None
        svc = SessionService(mock_redis)
        result = await svc.get_session(str(uuid.uuid4()))
        assert result is None


# ── Endpoint Tests ─────────────────────────────────────────────────────────────

class TestBotMessage:

    @pytest.mark.asyncio
    async def test_new_session_created_without_session_id(self, async_client, mock_redis):
        """POST /bot/message without sessionId creates new session."""
        from main import app
        from redis_client import get_redis
        from http_client import get_http_client
        
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_http_client] = lambda: AsyncMock()
        
        try:
            response = await async_client.post(
                "/api/v1/bot/message",
                json={"message": "I was defrauded via UPI transfer"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "success"
            assert "sessionId" in body["data"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_session_not_found_returns_404(self, async_client, mock_redis):
        """GET /bot/session/:id for expired session → 404."""
        from main import app
        from redis_client import get_redis
        
        app.dependency_overrides[get_redis] = lambda: mock_redis
        try:
            response = await async_client.get(
                f"/api/v1/bot/session/{uuid.uuid4()}",
            )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_whatsapp_webhook_returns_ack(self, async_client):
        """POST /bot/whatsapp always returns acknowledged."""
        response = await async_client.post(
            "/api/v1/bot/whatsapp",
            json={"from": "+919876543210", "message": "Help"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["acknowledged"] is True

    @pytest.mark.asyncio
    async def test_liveness(self, async_client):
        response = await async_client.get("/health/live")
        assert response.status_code == 200
