"""
MFA Service — TOTP-based multi-factor authentication.
Uses pyotp for TOTP generation and verification.

MFA flow:
  1. User logs in → if mfa_enabled, generate mfa_session_token → store {user_id} in Redis (5min TTL)
  2. Client calls POST /auth/mfa/verify with mfa_session_token + totpCode
  3. Service: look up user_id from Redis → fetch mfa_secret_enc → verify TOTP → issue JWT pair

Security note: mfa_secret_enc is stored in DB as a base64-encoded string.
For hackathon: no encryption applied (plaintext base64 TOTP secret).
Production: encrypt with AES-256-GCM using a key from Vault.
(Recorded in surjit/notes/assumptions.md)
"""
import base64
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.schemas import MFAVerifyResponse
from repositories.session_repository import SessionRepository
from repositories.user_repository import UserRepository
from security.jwt import create_token_pair


_MFA_SESSION_TTL = 300   # 5 minutes (from docs/db/redis.md)


class MFAService:

    class MFASessionExpiredError(Exception):
        pass

    class InvalidTOTPError(Exception):
        pass

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._user_repo = UserRepository(db)
        self._session_repo = SessionRepository(db)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def generate_totp_secret(self) -> str:
        """Generate a new random TOTP secret (base32 encoded, 32 chars)."""
        return pyotp.random_base32()

    def get_provisioning_uri(self, secret: str, email: str) -> str:
        """Return otpauth:// URI for QR code generation in authenticator apps."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(
            name=email,
            issuer_name=settings.MFA_TOTP_ISSUER,
        )

    async def enable_mfa(self, user_id: uuid.UUID, secret: str) -> str:
        """
        Enable MFA for a user. Stores encoded secret in DB.
        Returns the provisioning URI for QR code display.
        """
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Encode secret (plaintext for hackathon; see assumptions.md)
        encoded = base64.b64encode(secret.encode()).decode()
        async with self._db.begin():
            await self._user_repo.update_mfa(
                user_id=user_id,
                mfa_enabled=True,
                mfa_secret_enc=encoded,
            )
        return self.get_provisioning_uri(secret, user.email)

    # ── Verification ──────────────────────────────────────────────────────────

    def verify_totp(self, secret_enc: str, code: str) -> bool:
        """Verify a TOTP code against the stored (encoded) secret."""
        # Decode from base64
        secret = base64.b64decode(secret_enc.encode()).decode()
        totp = pyotp.TOTP(secret)
        # valid_window=1 allows 30s clock drift (one interval before/after)
        return totp.verify(code, valid_window=1)

    async def verify_mfa(self, mfa_session_token: str, totp_code: str) -> MFAVerifyResponse:
        """
        Complete MFA login:
        1. Retrieve user_id from Redis MFA session.
        2. Fetch user + MFA secret from DB.
        3. Verify TOTP code.
        4. Issue JWT pair.
        """
        redis_key = f"auth:mfa:{mfa_session_token}"
        user_id_str = await self._redis.get(redis_key)

        if not user_id_str:
            raise MFAService.MFASessionExpiredError("MFA session expired or invalid")

        user_id = uuid.UUID(user_id_str)
        user = await self._user_repo.get_by_id(user_id)
        if not user or not user.mfa_secret_enc:
            raise MFAService.MFASessionExpiredError("User or MFA config not found")

        if not self.verify_totp(user.mfa_secret_enc, totp_code):
            raise MFAService.InvalidTOTPError("TOTP code is incorrect")

        # Consume the MFA session (prevent replay)
        await self._redis.delete(redis_key)

        # Issue full JWT pair
        async with self._db.begin():
            access_token, refresh_token = await create_token_pair(user, self._db, self._session_repo)

        return MFAVerifyResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
