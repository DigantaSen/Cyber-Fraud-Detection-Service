"""
Pydantic schemas for Auth Service API.
Field names match docs/api/auth.md exactly.
"""
import uuid
import re
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ── Shared ────────────────────────────────────────────────────────────────────

class CurrentUser(BaseModel):
    """Decoded JWT claims. Passed via Depends(get_current_user)."""
    user_id: uuid.UUID
    email: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None
    jti: str  # JWT ID — used for denylist check


# ── Register ──────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    phone: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"CITIZEN", "INVESTIGATOR", "BANK_OFFICIAL", "TELECOM_ADMIN", "GOV_OFFICIAL"}
        if v not in allowed:
            raise ValueError(f"role must be one of {allowed}")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("password must contain at least one digit")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not re.match(r"^\+[1-9][0-9]{7,14}$", v):
            raise ValueError("phone must be in E.164 format (e.g. +919876543210)")
        return v

    @model_validator(mode="after")
    def validate_jurisdiction(self) -> "RegisterRequest":
        if self.role != "CITIZEN" and not self.jurisdiction_id:
            raise ValueError("jurisdiction_id is required for roles other than CITIZEN")
        return self


class RegisterResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str
    mfa_required: bool


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: int = 3600
    mfa_required: bool = False
    mfa_session_token: Optional[str] = None


# ── MFA ───────────────────────────────────────────────────────────────────────

class MFAVerifyRequest(BaseModel):
    mfa_session_token: str
    totp_code: str = Field(..., min_length=6, max_length=6)


class MFAVerifyResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int = 3600


# ── Refresh ───────────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int = 3600


# ── Me ────────────────────────────────────────────────────────────────────────

class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str
    org_id: Optional[uuid.UUID] = None
    jurisdiction_id: Optional[str] = None
