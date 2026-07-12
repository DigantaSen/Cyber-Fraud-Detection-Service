# Auth Service — API Contract
**Service:** `auth` | **Port:** 8000 | **Owner:** Surjit | **Task:** T4
**Kong prefix:** `/api/v1/auth` (no JWT required — auth is the issuer)
**Rate limit:** 20 req/min per IP (stricter than global — brute-force protection)

> See [_shared_contract.md](./_shared_contract.md) for envelope, pagination, and health conventions.

---

## Endpoints

### POST /auth/register
Register a new user account.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "min-8-chars",
  "phone": "+919876543210",
  "role": "CITIZEN",
  "orgId": "org-uuid",
  "jurisdictionId": "JUR_MH_MUMBAI"
}
```

**Constraints:**
- `role`: enum `[CITIZEN, INVESTIGATOR, BANK_OFFICIAL, TELECOM_ADMIN, GOV_OFFICIAL]`
- `password`: min 8 chars, 1 uppercase, 1 digit
- `phone`: E.164 format required
- `jurisdictionId`: required for non-CITIZEN roles
- Requires `Idempotency-Key` header

**Response 201:**
```json
{
  "data": {
    "userId": "uuid-v4",
    "email": "user@example.com",
    "role": "CITIZEN",
    "mfaRequired": false
  }
}
```

**Errors:**
- `409 DUPLICATE_EMAIL` — email already registered
- `400 INVALID_ROLE` — role not in allowed enum
- `400 WEAK_PASSWORD`

**Events published:** `User.Registered`

---

### POST /auth/login
Authenticate and receive a JWT pair.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "secret"
}
```

**Response 200:**
```json
{
  "data": {
    "accessToken": "<RS256 JWT>",
    "refreshToken": "<opaque token>",
    "expiresIn": 3600,
    "mfaRequired": true,
    "mfaSessionToken": "<short-lived token if mfaRequired=true>"
  }
}
```

**Notes:**
- If `mfaRequired=true`, the `accessToken` is NOT returned; client must call `/auth/mfa/verify` with the `mfaSessionToken`.
- Failed login increments a Redis counter (`auth:fail:{email}`). After 5 failures in 10 min, account is soft-locked for 15 min.

**Events published:** `User.LoginFailed` (on failure only)

---

### POST /auth/mfa/verify
Complete MFA with TOTP code.

**Request:**
```json
{
  "mfaSessionToken": "<from login response>",
  "totpCode": "123456"
}
```

**Response 200:**
```json
{
  "data": {
    "accessToken": "<RS256 JWT>",
    "refreshToken": "<opaque token>",
    "expiresIn": 3600
  }
}
```

**Errors:**
- `401 INVALID_TOTP` — wrong code
- `401 MFA_SESSION_EXPIRED` — session token expired (TTL 5 min)

---

### POST /auth/refresh
Exchange a refresh token for a new access token.

**Request:**
```json
{
  "refreshToken": "<opaque token>"
}
```

**Response 200:**
```json
{
  "data": {
    "accessToken": "<new RS256 JWT>",
    "expiresIn": 3600
  }
}
```

**Errors:**
- `401 REFRESH_TOKEN_INVALID` — revoked or expired

---

### POST /auth/logout
Revoke the current access token (add to JWT denylist in Redis).

**Headers:** `Authorization: Bearer <token>`

**Response 200:** `{"data": {"message": "Logged out"}}`

**Implementation note:** Stores JWT `jti` claim in Redis key `auth:denylist:{jti}` with TTL = remaining token expiry.

---

### GET /auth/me
Return current user profile from JWT claims (no DB call).

**Headers:** `Authorization: Bearer <token>`

**Response 200:**
```json
{
  "data": {
    "userId": "uuid",
    "email": "user@example.com",
    "role": "INVESTIGATOR",
    "orgId": "org-uuid",
    "jurisdictionId": "JUR_MH_MUMBAI"
  }
}
```
