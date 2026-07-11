# Bank BFF, Telecom BFF & Gov BFF — API Contract
**Services:** `bank-bff`, `telecom-bff`, `gov-bff` | **Owner:** Diganta | **Task:** T4c
**Kong prefixes:** `/api/v1/bank`, `/api/v1/telecom`, `/api/v1/gov`

> See [_shared_contract.md](./_shared_contract.md) for envelope and health conventions.

---

## Common Notes

All three BFFs are **lightweight FastAPI gateway services**. They:
- Validate JWT and enforce role-based access
- Inject `correlationId` and `jurisdictionId` into downstream calls
- Are stateless — no local data storage

---

# Bank BFF
**Kong prefix:** `/api/v1/bank`
**Required JWT role:** `BANK_OFFICIAL`

## Endpoints

### GET /bank/transactions/flagged
Get a paginated list of flagged/blocked bank transactions with AI risk scores.

**BFF orchestration:** Calls `GET /search/cases?complaintType=UPI_FRAUD&riskTier=HIGH` on Search Service, filtered to cases with `Transaction.Ingested` origin.

**Query params:** `cursor`, `limit`, `riskTier`, `from`, `to`

**Response 200:**
```json
{
  "items": [
    {
      "caseId": "uuid",
      "transactionId": "TXN-XYZ789",
      "fromAccount": "XXXXXX1234",
      "toAccount": "XXXXXX5678",
      "amountINR": 50000.00,
      "fusedScore": 94,
      "riskTier": "CRITICAL",
      "decision": "BLOCKED",
      "blockReason": "Linked to active fraud ring — 3 previously flagged accounts.",
      "timestamp": "2026-07-11T12:00:00Z"
    }
  ],
  "nextCursor": null,
  "hasMore": false,
  "total": 12
}
```

---

### GET /bank/stream
SSE stream for real-time transaction block notifications.

**BFF orchestration:** Proxies to `GET /notify/stream` on Notification Service, filtered to `BANK_OFFICIAL` events.

**Response:** SSE stream, events:
```
event: transaction_blocked
data: {"transactionId":"TXN-XYZ789","amountINR":50000,"riskTier":"CRITICAL"}
```

---

# Telecom BFF
**Kong prefix:** `/api/v1/telecom`
**Required JWT role:** `TELECOM_ADMIN`

## Endpoints

### GET /telecom/sessions/active
Get a rolling log of currently flagged/interdicted call sessions.

**BFF orchestration:** Calls `GET /search/cases?complaintType=CALL_FRAUD&status=Investigating` on Search Service.

**Query params:** `cursor`, `limit`

**Response 200:**
```json
{
  "items": [
    {
      "caseId": "uuid",
      "sessionId": "SESS-ABC123",
      "callerPhone": "+919876543210",
      "calleePhone": "+919000000001",
      "interdictionDecision": "BLOCK",
      "fusedScore": 96,
      "riskTier": "CRITICAL",
      "detectedAt": "2026-07-11T12:00:00Z",
      "carrier": "Airtel"
    }
  ],
  "nextCursor": null,
  "hasMore": false,
  "total": 4
}
```

---

### GET /telecom/stream
SSE stream for real-time interdiction alerts.

**BFF orchestration:** Proxies to `GET /notify/stream` filtered to `TELECOM_ADMIN` events.

```
event: call_interdicted
data: {"sessionId":"SESS-ABC123","callerPhone":"+919876543210","decision":"BLOCK"}
```

---

# Gov BFF
**Kong prefix:** `/api/v1/gov`
**Required JWT role:** `GOV_OFFICIAL`

## Endpoints

### GET /gov/alerts
Get high-priority MHA alerts stream.

**BFF orchestration:** Calls Notification Service audit log for `MHAAlert.Sent` events.

**Query params:** `cursor`, `limit`, `from`, `to`

**Response 200:**
```json
{
  "items": [
    {
      "alertId": "uuid",
      "alertType": "FRAUD_RING_DETECTED",
      "riskTier": "CRITICAL",
      "summary": "Detected fraud ring of 7 nodes...",
      "jurisdictionId": "JUR_MH_MUMBAI",
      "suspects": ["+919876543210"],
      "dispatchedAt": "2026-07-11T12:00:03Z"
    }
  ],
  "nextCursor": null,
  "hasMore": false,
  "total": 3
}
```

---

### GET /gov/reports
List available NCRB reports and intelligence packages.

**BFF orchestration:** Proxies to `GET /reports` on Reporting Service.

**Response 200:** Paginated list of reports (see [reporting.md](./reporting.md)).

---

### POST /gov/reports/intelligence-package
Request a new intelligence package for a case.

**BFF orchestration:** Proxies to `POST /reports/intelligence-package` on Reporting Service.

**Request/Response:** See [reporting.md](./reporting.md).

---

### GET /gov/stream
SSE stream for real-time national-level alerts.

**BFF orchestration:** Proxies to `GET /notify/stream` filtered to `GOV_OFFICIAL` events.

```
event: mha_alert
data: {"alertId":"uuid","riskTier":"CRITICAL","summary":"..."}
```
