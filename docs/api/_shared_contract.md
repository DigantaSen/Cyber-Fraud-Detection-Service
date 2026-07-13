# Shared API Contract Conventions
**Version:** v1 | **Owner:** Diganta | **Status:** FROZEN (Day 1 EOD)

> All services implement these conventions without exception. Any deviation must be explicitly noted in the service's own contract file and approved by all 4 team members.

---

## Base URL
All routes are exposed through the Kong API Gateway and versioned under `/api/v1/`.

| Portal / Access | Kong prefix | Downstream service |
|---|---|---|
| Citizen UI | `/api/v1/citizen/` | `citizen-bff:8000` |
| Investigator UI | `/api/v1/investigator/` | `investigator-bff:8000` |
| Bank Portal | `/api/v1/bank/` | `department-bffs:8000` |
| Telecom Portal | `/api/v1/telecom/` | `department-bffs:8000` |
| Gov Portal | `/api/v1/gov/` | `department-bffs:8000` |
| Auth (public) | `/api/v1/auth/` | `auth:8000` |
| Search (public read) | `/api/v1/search/` | `search:8000` |
| Events (M2M webhook) | `/api/v1/events/` | `event-processing:8000` |

> **Internal service-to-service calls** (never exposed at Kong) use `http://<service-name>:8000` on the Docker bridge network (`172.20.0.0/16`).

---

## Authentication

Every protected route requires:
```
Authorization: Bearer <RS256-signed JWT>
```
Kong validates JWT signature and expiry (`exp` claim). Services only enforce fine-grained resource authorization using claims from the decoded token.

**Standard JWT Claims:**
| Claim | Type | Description |
|---|---|---|
| `sub` | string | User UUID |
| `role` | string | `CITIZEN`, `INVESTIGATOR`, `BANK_OFFICIAL`, `TELECOM_ADMIN`, `GOV_OFFICIAL`, `ADMIN` |
| `orgId` | string | Organisation UUID |
| `jurisdictionId` | string | Geographic jurisdiction code |
| `exp` | integer | Expiry (Unix timestamp) |
| `kid` | string | Key ID for RS256 public key lookup |

---

## Standard Response Envelope

**Success:**
```json
{
  "requestId": "uuid-v4",
  "correlationId": "uuid-v4",
  "timestamp": "2026-07-11T12:00:00Z",
  "status": "success",
  "data": { ... }
}
```

**Error:**
```json
{
  "requestId": "uuid-v4",
  "correlationId": "uuid-v4",
  "timestamp": "2026-07-11T12:00:00Z",
  "status": "error",
  "errorCode": "CASE_NOT_FOUND",
  "message": "Human-readable description",
  "details": { ... }
}
```

---

## HTTP Status Codes

| Code | Usage |
|---|---|
| 200 | Successful GET / PATCH |
| 201 | Successful POST (resource created) |
| 202 | Accepted (async processing triggered) |
| 400 | Validation error |
| 401 | Missing or invalid JWT |
| 403 | Insufficient RBAC permissions |
| 404 | Resource not found |
| 409 | Conflict / duplicate |
| 422 | Business rule violation |
| 429 | Rate limit exceeded |
| 503 | Circuit breaker open / downstream unavailable |

---

## Idempotency

All `POST` endpoints that create resources require:
```
Idempotency-Key: <client-generated uuid-v4>
```
If the same key is sent within 24h, the server returns the original response without re-processing (status 200 with original body).

---

## Cursor-Based Pagination

All list endpoints:
- Query params: `?cursor=<opaque_base64>&limit=<n>` (default limit=20, max=100)
- Response:
```json
{
  "items": [...],
  "nextCursor": "<base64_or_null>",
  "hasMore": true,
  "total": 1234
}
```
Cursor encodes `(created_at, id)` for stable ordering under concurrent inserts.

**Endpoints requiring pagination:** `/cases`, `/evidence`, `/audit/case/:id`, `/graph/linkages`, `/reports`, `/search/cases`

---

## Rate Limit Headers

Every response includes:
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 987
X-RateLimit-Reset: 1752240000
Retry-After: 30   (only on 429)
```

Circuit breaker 503 responses include:
```
Retry-After: <seconds_until_circuit_resets>
```

---

## Health Endpoints (every service)

| Route | Description |
|---|---|
| `GET /health/live` | Liveness — process is running. Returns `{"status":"ok"}` |
| `GET /health/ready` | Readiness — checks DB, Kafka, Redis. Returns `{"status":"ok","checks":{...}}` |
| `GET /metrics` | Prometheus text format (auto via `prometheus-fastapi-instrumentator`) |

Kubernetes uses `/health/live` for liveness probe and `/health/ready` for readiness probe.

---

## Correlation ID Propagation

Kong injects `X-Correlation-ID` on every inbound request. All services must:
1. Read `X-Correlation-ID` from request header
2. Log it in every structured log line
3. Forward it in every downstream HTTP/Kafka call as `X-Correlation-ID` and include it in the response envelope `correlationId` field.

---

## Hackathon vs Production Notes

> Unless explicitly stated in a contract file, all endpoints are **fully implemented** for the hackathon demo. Exceptions are called out with `[STUB]` tags.
