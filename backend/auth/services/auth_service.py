"""
Auth Service — core business logic.
Orchestrates: register, login (with brute-force protection), refresh, logout.
Does NOT touch DB directly — delegates to repositories.
Does NOT sign JWTs — delegates to security/jwt.py (Prompt 006).
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.schemas import (
    LoginRequest, LoginResponse,
    RefreshRequest, RefreshResponse,
    RegisterRequest, RegisterResponse,
)
from repositories.idempotency_repository import IdempotencyRepository
from repositories.session_repository import SessionRepository
from repositories.user_repository import UserRepository
from security.password import hash_password, verify_password


# ── Constants (from docs/api/auth.md) ─────────────────────────────────────────
_MAX_FAILURES = 5
_FAILURE_WINDOW_SECONDS = 600    # 10 minutes
_LOCK_DURATION_SECONDS = 900     # 15 minutes
_MFA_SESSION_TTL_SECONDS = 300   # 5 minutes


class AuthService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._user_repo = UserRepository(db)
        self._session_repo = SessionRepository(db)
        self._idempotency_repo = IdempotencyRepository(db)

    # ── Register ──────────────────────────────────────────────────────────────

    async def register(self, req: RegisterRequest, idempotency_key: uuid.UUID) -> RegisterResponse:
        """Register a new user. Idempotent — same key returns cached response."""

        # Check idempotency
        existing = await self._idempotency_repo.get(idempotency_key)
        if existing:
            return RegisterResponse(**existing.response_body["data"])

        # Check duplicate email
        if await self._user_repo.get_by_email(req.email):
            raise DuplicateEmailError(req.email)

        # Create user
        user = await self._user_repo.create(
            email=req.email,
            password_hash=hash_password(req.password),
            phone=req.phone,
            role=req.role,
            org_id=req.org_id,
            jurisdiction_id=req.jurisdiction_id,
        )
        response_data = {
            "user_id": str(user.user_id),
            "email": user.email,
            "role": user.role,
            "mfa_required": False,
        }
        await self._idempotency_repo.store(
            idempotency_key=idempotency_key,
            request_hash=_hash_request(req.model_dump()),
            response_status=201,
            response_body={"data": response_data},
        )
        await self._db.commit()

        return RegisterResponse(**response_data)

    # ── Login ─────────────────────────────────────────────────────────────────

    async def login(self, req: LoginRequest) -> LoginResponse:
        """
        Authenticate user. Returns JWT pair or MFA session token.
        Enforces brute-force protection via Redis counters.
        """
        email_lower = req.email.lower()

        # Check soft lock
        if await self._redis.exists(f"auth:lock:{email_lower}"):
            raise AccountLockedError(email_lower)

        # Look up user
        user = await self._user_repo.get_by_email(email_lower)
        if not user or not verify_password(req.password, user.password_hash):
            # Increment failure counter
            await _increment_failure(self._redis, email_lower)
            raise InvalidCredentialsError()

        # Reset failure counter on success
        await self._redis.delete(f"auth:fail:{email_lower}")

        # Update last login
        await self._user_repo.update_last_login(user.user_id)
        await self._db.commit()

        # MFA required?
        if user.mfa_enabled:
            mfa_token = secrets.token_urlsafe(32)
            await self._redis.setex(
                f"auth:mfa:{mfa_token}",
                _MFA_SESSION_TTL_SECONDS,
                str(user.user_id),
            )
            return LoginResponse(mfa_required=True, mfa_session_token=mfa_token)

        # Issue JWT pair (jwt.py will be wired in Prompt 007)
        # For now: return a stub that will be replaced
        from security.jwt import create_token_pair
        access_token, refresh_token = await create_token_pair(user, self._db, self._session_repo)
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            mfa_required=False,
        )

    # ── Refresh ───────────────────────────────────────────────────────────────

    async def refresh(self, req: RefreshRequest) -> RefreshResponse:
        """Exchange a valid refresh token for a new access token."""
        token_hash = hashlib.sha256(req.refresh_token.encode()).hexdigest()
        db_session = await self._session_repo.get_by_token_hash(token_hash)
        if not db_session:
            raise InvalidRefreshTokenError()

        user = await self._user_repo.get_by_id(db_session.user_id)
        if not user or user.status != "ACTIVE":
            raise InvalidRefreshTokenError()

        from security.jwt import sign_access_token
        access_token = sign_access_token(user)
        return RefreshResponse(
            access_token=access_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    # ── Logout ────────────────────────────────────────────────────────────────

    async def logout(self, jti: str, token_exp: int, token_hash: str) -> None:
        """Add JWT to denylist and revoke session."""
        # Denylist the access token JTI
        ttl = max(0, token_exp - int(datetime.now(timezone.utc).timestamp()))
        if ttl > 0:
            await self._redis.setex(f"auth:denylist:{jti}", ttl, "1")

        # Revoke refresh session
        db_session = await self._session_repo.get_by_token_hash(token_hash)
        if db_session:
            await self._session_repo.revoke(db_session.session_id)
            await self._db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_request(data: dict) -> str:
    """Deterministic hash of request body for idempotency comparison."""
    import json
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


async def _increment_failure(redis: aioredis.Redis, email: str) -> None:
    """Increment failure counter; lock account on threshold."""
    key = f"auth:fail:{email}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _FAILURE_WINDOW_SECONDS)
    if count >= _MAX_FAILURES:
        await redis.setex(f"auth:lock:{email}", _LOCK_DURATION_SECONDS, "1")


# ── Domain Exceptions (caught and mapped to HTTP errors in router) ─────────────

class DuplicateEmailError(Exception):
    def __init__(self, email: str):
        self.email = email

class AccountLockedError(Exception):
    def __init__(self, email: str):
        self.email = email

class InvalidCredentialsError(Exception):
    pass

class InvalidRefreshTokenError(Exception):
    pass
