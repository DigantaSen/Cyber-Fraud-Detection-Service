"""
Idempotency Repository — platform.idempotency_keys table.
Used by all mutating POST/PATCH endpoints in the Case Service.
Pattern copied from backend/auth/repositories/idempotency_repository.py.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.idempotency import IdempotencyKey


class IdempotencyRepository:

    SERVICE_NAME = "case-service"

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, idempotency_key: uuid.UUID) -> IdempotencyKey | None:
        """Return cached response if this key was already processed, else None."""
        result = await self._session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.service_name == self.SERVICE_NAME,
                IdempotencyKey.idempotency_key == idempotency_key,
                IdempotencyKey.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none()

    async def store(
        self,
        idempotency_key: uuid.UUID,
        request_hash: str,
        response_status: int,
        response_body: dict,
    ) -> None:
        """Store the result of a successfully processed request (TTL = 24 h)."""
        now = datetime.now(timezone.utc)
        record = IdempotencyKey(
            service_name=self.SERVICE_NAME,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        self._session.add(record)
        await self._session.flush()
