"""
User Repository — all DB operations on identity.users.
Only this layer may access the database for user data.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User


class UserRepository:

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        """Case-insensitive email lookup (uses users_email_lower_uidx)."""
        result = await self._session.execute(
            select(User).where(User.email.ilike(email))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def create(
        self,
        email: str,
        password_hash: str,
        phone: str,
        role: str,
        org_id: uuid.UUID | None = None,
        jurisdiction_id: str | None = None,
    ) -> User:
        """Create and persist a new user. Caller must commit the session."""
        now = datetime.now(timezone.utc)
        user = User(
            email=email.lower(),   # Normalize to lowercase
            password_hash=password_hash,
            phone=phone,
            role=role,
            org_id=org_id,
            jurisdiction_id=jurisdiction_id,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        self._session.add(user)
        await self._session.flush()  # Populate user_id without committing
        return user

    async def update_status(self, user_id: uuid.UUID, status: str) -> None:
        """Update user status (ACTIVE, SOFT_LOCKED, DISABLED)."""
        await self._session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(status=status, updated_at=datetime.now(timezone.utc))
        )

    async def update_last_login(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(last_login_at=datetime.now(timezone.utc))
        )

    async def update_mfa(self, user_id: uuid.UUID, mfa_enabled: bool, mfa_secret_enc: str) -> None:
        """Enable MFA and store encrypted TOTP secret."""
        await self._session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(
                mfa_enabled=mfa_enabled,
                mfa_secret_enc=mfa_secret_enc,
                updated_at=datetime.now(timezone.utc),
            )
        )
