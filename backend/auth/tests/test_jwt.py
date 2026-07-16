"""Unit tests for JWT signing and verification."""
import uuid
import pytest
from unittest.mock import AsyncMock, patch

from security.jwt import sign_access_token, decode_token, get_current_user
from models.user import User
from models.schemas import CurrentUser


@pytest.fixture
def sample_user():
    return User(
        user_id=uuid.uuid4(),
        email="jwt_test@example.com",
        role="INVESTIGATOR",
        org_id=uuid.uuid4(),
        jurisdiction_id="JUR_MH_MUMBAI",
        status="ACTIVE",
    )


def test_sign_and_decode_token(sample_user):
    """Token signed with private key should be decodable with public key."""
    token = sign_access_token(sample_user)
    assert token  # Non-empty

    payload = decode_token(token)
    assert payload["sub"] == str(sample_user.user_id)
    assert payload["role"] == "INVESTIGATOR"
    assert payload["jurisdictionId"] == "JUR_MH_MUMBAI"
    assert "jti" in payload
    assert "exp" in payload


def test_token_contains_required_claims(sample_user):
    """All claims from _shared_contract.md must be present."""
    token = sign_access_token(sample_user)
    payload = decode_token(token)
    required_claims = {"sub", "role", "jti", "exp", "iat", "kid"}
    assert required_claims.issubset(set(payload.keys()))
