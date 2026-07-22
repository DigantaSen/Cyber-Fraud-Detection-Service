# Case Management Service — API Contract
**Service:** `case` | **Port:** 8000 | **Owner:** Surjit | **Task:** T5a
**Internal only** — accessed by BFFs, not directly exposed at Kong.

> See [_shared_contract.md](./_shared_contract.md) for envelope, pagination, and health conventions.

---

## State Machine

```
New → Assigned → Investigating → Pending_AI → Investigating (on AI timeout)
                                            → Action_Taken → Closed
```

Valid transitions enforced server-side. Any invalid transition returns `422 INVALID_STATE_TRANSITION`.

---

## Endpoints

### POST /cases
Create a new investigation case.

**Headers:** `Authorization: Bearer <JWT>` | `Idempotency-Key: <uuid>`

**Request:**
```json
{
  "title": "Suspected UPI fraud",
  "description": "Received a fraudulent UPI payment request from +919876543210",
  "complaintType": "UPI_FRAUD",
  "suspectPhone": "+919876543210",
  "suspectAccount": "XXXXXX1234",
  "complaintLat": 19.0760,
  "complaintLon": 72.8777,
  "reporterEntityName": "John Doe",
  "reporterPhone": "+919000000001",
  "languageCode": "en"
}
```

**Constraints:**
- `complaintType`: enum `[UPI_FRAUD, CALL_FRAUD, COUNTERFEIT_CURRENCY, CYBER_CRIME, OTHER]`
- `suspectPhone`: E.164 format if provided
- `complaintLat`/`complaintLon`: valid WGS84 coordinates
- `languageCode`: BCP-47 code (e.g. `hi`, `bn`, `te`, `ta`, `mr`, `gu`, `kn`, `ml`, `pa`, `ur`, `or`, `as`, `en`)

**Response 201:**
```json
{
  "data": {
    "caseId": "uuid-v4",
    "caseNumber": "CYB-2026-00001",
    "status": "New",
    "createdAt": "2026-07-11T12:00:00Z",
    "assignedTo": null,
    "predictionStatus": "PENDING"
  }
}
```

**Side effects:**
- Persists case to PostgreSQL
- Writes `Case.Created` event to Outbox table
- Outbox publisher relays `Case.Created` to Kafka → triggers Orchestrator, Geo consumer, Entity Graph consumer, Search consumer

**Errors:**
- `409 DUPLICATE_CASE` — same `Idempotency-Key`

---

### GET /cases/:caseId
Get full case detail.

**Response 200:**
```json
{
  "data": {
    "caseId": "uuid",
    "caseNumber": "CYB-2026-00001",
    "status": "Investigating",
    "title": "Suspected UPI fraud",
    "description": "...",
    "complaintType": "UPI_FRAUD",
    "suspectPhone": "+919876543210",
    "complaintLat": 19.076,
    "complaintLon": 72.877,
    "reporterEntityName": "John Doe",
    "reporterPhone": "+919000000001",
    "languageCode": "en",
    "assignedTo": "investigator-uuid",
    "jurisdictionId": "JUR_MH_MUMBAI",
    "prediction": {
      "predictionId": "uuid",
      "fusedScore": 87.5,
      "riskTier": "HIGH",
      "confidence": 0.91,
      "status": "COMPLETE",
      "modelBreakdown": [
        {"model": "scam-nlp", "score": 92, "confidence": 0.95},
        {"model": "graph-analyzer", "score": 83, "confidence": 0.88}
      ],
      "explanation": "Suspect linked to 3 previously flagged accounts. NLP detected urgency pressure language.",
      "createdAt": "2026-07-11T12:00:30Z"
    },
    "evidenceCount": 2,
    "createdAt": "2026-07-11T12:00:00Z",
    "updatedAt": "2026-07-11T12:01:00Z"
  }
}
```

**Errors:** `404 CASE_NOT_FOUND`

---

### GET /cases
List cases (paginated). RBAC-scoped by `jurisdictionId` from JWT.

**Query params:**
- `cursor`, `limit` (see shared pagination)
- `status`: filter by state
- `riskTier`: `LOW|MEDIUM|HIGH|CRITICAL`
- `assignedTo`: investigator UUID

**Response 200:** Paginated list of case summaries (subset of full case fields).

---

### PATCH /cases/:caseId/state
Transition case to a new state.

**Headers:** `Authorization: Bearer <JWT>` | `Idempotency-Key: <uuid>`

**Request:**
```json
{
  "state": "Assigned",
  "reason": "Assigned to investigator after initial review",
  "assignedTo": "investigator-uuid"
}
```

**Allowed callers by role:**
- `INVESTIGATOR`, `ADMIN`: all transitions
- Orchestrator service (internal): `Pending_AI → Investigating` (AI_TIMEOUT reason only)

**Response 200:** Updated case summary.

**Events published:** `Case.Updated`, `Case.Assigned` (if assigning)

---

### PATCH /cases/:caseId/verdict/override
Investigator HITL override of AI verdict.

**Headers:** `Authorization: Bearer <JWT>` (role: `INVESTIGATOR` or `ADMIN`)
**Idempotency-Key required.**

**Request:**
```json
{
  "decision": "APPROVE",
  "justification": "Reviewed all evidence. NLP score accurate. Approving automated actions.",
  "originalVerdictId": "prediction-uuid"
}
```

**Constraints:**
- `decision`: enum `[APPROVE, REJECT]`
- `justification`: required, min 20 chars (legal requirement — NFR-8.4)
- Case must be in `Pending_AI` or `Action_Taken` state

**Response 200:**
```json
{
  "data": {
    "overrideId": "uuid",
    "decision": "APPROVE",
    "caseId": "uuid",
    "investigatorId": "uuid",
    "originalVerdictId": "uuid",
    "timestamp": "2026-07-11T12:05:00Z"
  }
}
```

**Side effects:**
- Persists immutable `OverrideRecord` to DB
- `APPROVE` → resumes suppressed automated actions (MHA alert, notifications)
- `REJECT` → moves case to `Closed` with disposition `FALSE_POSITIVE`
- Publishes `Prediction.Overridden` → Audit Service

---

### GET /cases/:caseId/timeline
Chronological audit timeline for a case (cursor-paginated).

**Response 200:**
```json
{
  "items": [
    {
      "eventType": "Case.Created",
      "actor": "system",
      "description": "Case created via Citizen BFF",
      "timestamp": "2026-07-11T12:00:00Z"
    },
    {
      "eventType": "Case.Assigned",
      "actor": "investigator-uuid",
      "description": "Assigned to Inspector Sharma",
      "timestamp": "2026-07-11T12:01:00Z"
    }
  ],
  "nextCursor": null,
  "hasMore": false,
  "total": 2
}
```
