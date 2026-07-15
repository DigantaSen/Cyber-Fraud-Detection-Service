"""
Session Repository — DB operations on identity.sessions.
Stores refresh token HASHES only (never plaintext tokens).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.session import Session


class SessionRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        user_id: uuid.UUID,
        refresh_token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> Session:
        """Create a new session record. Caller must commit."""
        db_session = Session(
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(db_session)
        await self._session.flush()
        return db_session

    async def get_by_token_hash(self, token_hash: str) -> Session | None:
        """Find active (non-revoked, non-expired) session by refresh token hash."""
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            select(Session).where(
                Session.refresh_token_hash == token_hash,
                Session.revoked_at.is_(None),
                Session.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, session_id: uuid.UUID) -> None:
        """Soft-revoke a session (never DELETE)."""
        await self._session.execute(
            update(Session)
            .where(Session.session_id == session_id)
            .values(revoked_at=datetime.now(timezone.utc))
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        """Revoke all active sessions for a user (e.g., on password change)."""
        now = datetime.now(timezone.utc)
        await self._session.execute(
            update(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
