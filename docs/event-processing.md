# Event Processing Service — API Contract
**Service:** `event-processing` | **Port:** 8000 | **Owner:** Diganta | **Task:** T8b
**Kong prefix:** `/api/v1/events` (no JWT — authenticated by HMAC signature)

> See [_shared_contract.md](./_shared_contract.md) for envelope and health conventions.

---

## Architecture

The Event Processing Service is the **async nervous system** and also handles the **<300ms synchronous interdiction path** (T15).

**Two paths:**
1. **Async path (standard):** Webhook receives external data → publishes Kafka event → returns immediately
2. **Sync path (interdiction):** Telecom event → direct HTTP to Orchestrator → get verdict → return block/allow decision within 300ms (bypasses Kafka)

**HMAC Authentication:** All webhook endpoints validate `X-HMAC-Signature` header:
```
X-HMAC-Signature: sha256=hex(HMAC-SHA256(secret, request_body))
```
Secrets stored in `.env`: `TELECOM_WEBHOOK_SECRET`, `BANK_WEBHOOK_SECRET`.

---

## Kafka Backbone (T8b)

**Topic provisioning (on service startup):**
```bash
/infra/kafka/provision-topics.sh
```

| Topic | Partitions | Retention |
|---|---|---|
| `case-events` | 12 | 7 days |
| `prediction-events` | 12 | 14 days |
| `audit-events` | 12 | 30 days |
| `telecom-events` | 12 | 3 days |
| `transaction-events` | 12 | 7 days |
| `notification-events` | 12 | 3 days |
| `geo-events` | 12 | 7 days |
| `entity-events` | 12 | 14 days |
| `evidence-events` | 12 | 14 days |
| `report-events` | 12 | 30 days |
| `*.DLQ` | 1 each | 30 days |

**Outbox Publisher:** Listens on PostgreSQL `LISTEN/NOTIFY` (`outbox_channel`). On notification, polls `outbox` table and publishes pending events via `kafka-python` with `enable.idempotence=true`, `acks=all`.

**DLQ Consumer:** 3 retries with exponential backoff (1s, 5s, 30s). After max retries → routes to `<topic>.DLQ`. Prometheus counter: `kafka_dlq_depth{topic="..."}`.

---

## Endpoints

### POST /events/telecom-stream
Ingest telecom call session event. Async path.

**Headers:** `X-HMAC-Signature: sha256=<hex>`

**Request:**
```json
{
  "sessionId": "SESS-ABC123",
  "callerPhone": "+919876543210",
  "calleePhone": "+919000000001",
  "eventType": "CALL_INITIATED",
  "durationSeconds": 0,
  "metadata": {
    "networkType": "4G",
    "location": {"lat": 19.076, "lon": 72.877},
    "carrier": "Airtel"
  },
  "timestamp": "2026-07-11T12:00:00Z"
}
```

**Constraints:**
- `eventType`: enum `[CALL_INITIATED, CALL_FLAGGED, CALL_TERMINATED, CALL_DROPPED]`

**Response 202:**
```json
{
  "data": {"acknowledged": true, "eventId": "uuid"}
}
```

**Events published:** `TelecomEvent.Ingested`, `CallSession.Initiated` / `CallSession.Flagged`

---

### POST /events/bank-transaction
Ingest bank transaction event. Async path.

**Headers:** `X-HMAC-Signature: sha256=<hex>`

**Request:**
```json
{
  "transactionId": "TXN-XYZ789",
  "fromAccount": "XXXXXX1234",
  "toAccount": "XXXXXX5678",
  "amountINR": 50000.00,
  "transactionType": "UPI",
  "timestamp": "2026-07-11T12:00:00Z",
  "metadata": {
    "upiId": "suspect@paytm",
    "deviceFingerprint": "IMEI123"
  }
}
```

**Response 202:** `{"data": {"acknowledged": true, "eventId": "uuid"}}`

**Events published:** `Transaction.Ingested`

---

### POST /events/interdict
**Synchronous interdiction path (<300ms SLA — T15).**
Bypasses Kafka entirely. Telecom system calls this for real-time scam call intervention.

**Headers:** `X-HMAC-Signature: sha256=<hex>`

**Request:**
```json
{
  "sessionId": "SESS-ABC123",
  "callerPhone": "+919876543210",
  "calleePhone": "+919000000001",
  "audioChunkBase64": "base64-encoded-audio-snippet (optional)",
  "complaintContext": "Caller claiming to be CBI officer"
}
```

**Response 200 (synchronous, max 300ms):**
```json
{
  "data": {
    "decision": "BLOCK",
    "confidence": 0.94,
    "riskTier": "CRITICAL",
    "fusedScore": 96,
    "interdictionId": "uuid",
    "reason": "NLP detected impersonation pattern + suspect linked to fraud ring",
    "latencyMs": 187
  }
}
```

**Decisions:** `BLOCK | ALLOW | PENDING_REVIEW`

**Side effects (after returning response):**
- Publishes `TelecomEvent.Ingested` + `Intervention.Requested` to Kafka asynchronously
- Kafka consumer writes to Audit Service for legal admissibility

**Events published (async, after response):** `Intervention.Requested`, `TelecomEvent.Ingested`
