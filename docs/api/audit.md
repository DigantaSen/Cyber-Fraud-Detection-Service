# Audit Service — API Contract
**Service:** `audit` | **Port:** 8000 | **Owner:** Diganta | **Task:** T7
**Internal only** — reads exposed via Investigator BFF only.

> See [_shared_contract.md](./_shared_contract.md) for envelope, pagination, and health conventions.

---

## Architecture

The Audit Service is a **pure Kafka consumer** — it has **no write API**. All writes are triggered by domain events from Kafka. The PostgreSQL `audit_log` table is **append-only** — no `UPDATE` or `DELETE` statements ever run against it.

**Kafka consumer groups:** `audit-consumer` — subscribes to ALL domain events (`Case.*`, `Evidence.*`, `Prediction.*`, `MHAAlert.*`, `User.*`, `Intervention.*`, `IntelligencePackage.*`, `Report.*`).

```sql
CREATE TABLE audit_log (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type   VARCHAR(128) NOT NULL,
  entity_type  VARCHAR(64) NOT NULL,
  entity_id    UUID NOT NULL,
  actor_id     UUID,
  actor_role   VARCHAR(64),
  payload      JSONB NOT NULL,  -- full event payload
  correlation_id UUID,
  created_at   TIMESTAMPTZ DEFAULT NOW()
  -- NO updated_at — append-only
);
CREATE INDEX ON audit_log (entity_id, created_at DESC);
CREATE INDEX ON audit_log (event_type, created_at DESC);
```

---

## Endpoints

### GET /audit/case/:caseId
Get the full immutable audit trail for a case (paginated, chronological).

**Headers:** `Authorization: Bearer <JWT>` (role: `INVESTIGATOR`, `ADMIN`)

**Query params:** `cursor`, `limit`

**Response 200:**
```json
{
  "items": [
    {
      "auditId": "uuid",
      "eventType": "Case.Created",
      "entityType": "Case",
      "entityId": "case-uuid",
      "actorId": "system",
      "actorRole": "SYSTEM",
      "payload": {
        "caseNumber": "CYB-2026-00001",
        "complaintType": "UPI_FRAUD"
      },
      "correlationId": "uuid",
      "createdAt": "2026-07-11T12:00:00Z"
    },
    {
      "auditId": "uuid",
      "eventType": "Prediction.Overridden",
      "entityType": "Prediction",
      "entityId": "prediction-uuid",
      "actorId": "investigator-uuid",
      "actorRole": "INVESTIGATOR",
      "payload": {
        "decision": "APPROVE",
        "justification": "...",
        "originalScore": 87.5
      },
      "correlationId": "uuid",
      "createdAt": "2026-07-11T12:05:00Z"
    }
  ],
  "nextCursor": null,
  "hasMore": false,
  "total": 8
}
```

**Errors:**
- `404 CASE_NOT_FOUND`
- `403 JURISDICTION_MISMATCH` — case not in caller's jurisdiction

---

### GET /audit/entity/:entityId
Get audit events for any entity type (case, prediction, evidence, etc.).

**Query params:** `entityType`, `from`, `to`, `cursor`, `limit`

**Response 200:** Same paginated structure as above.
