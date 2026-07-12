# Citizen BFF — API Contract
**Service:** `citizen-bff` | **Port:** 8000 | **Owner:** Surjit | **Task:** T4b
**Kong prefix:** `/api/v1/citizen` (JWT required, role: `CITIZEN`)
**Rate limit:** 60 req/min per authenticated user token

> See [_shared_contract.md](./_shared_contract.md) for envelope and health conventions.

---

## Architecture

The Citizen BFF is a **stateless aggregation gateway** that shields the Citizen UI from the internal service topology. It proxies requests to Case Service, Bot Service, and Evidence Service, injecting `correlationId` and `X-User-Context` into every downstream call.

---

## Endpoints

### POST /citizen/report
Submit a fraud report. Creates a new case and triggers async AI analysis.

**Headers:** `Authorization: Bearer <JWT>` | `Idempotency-Key: <uuid>`

**Request:**
```json
{
  "title": "Suspicious UPI payment request",
  "description": "Received a payment request for ₹50,000 claiming to be from CBI",
  "complaintType": "UPI_FRAUD",
  "suspectPhone": "+919876543210",
  "suspectAccount": "XXXXXX1234",
  "complaintLat": 19.076,
  "complaintLon": 72.877,
  "languageCode": "hi"
}
```

**BFF orchestration:**
1. `POST /cases` → Case Service → creates case, returns `caseId`
2. Case Service writes `Case.Created` to Outbox → triggers Orchestrator via Kafka

**Response 201:**
```json
{
  "data": {
    "caseId": "uuid",
    "caseNumber": "CYB-2026-00001",
    "message": "Your report has been registered. AI analysis is in progress.",
    "trackingUrl": "/citizen/cases/uuid"
  }
}
```

---

### GET /citizen/cases/:caseId
Get the status and AI verdict of a submitted report.

**BFF orchestration:** Single call to `GET /cases/:caseId` → Case Service.

**Response 200:**
```json
{
  "data": {
    "caseId": "uuid",
    "caseNumber": "CYB-2026-00001",
    "status": "Investigating",
    "prediction": {
      "riskTier": "HIGH",
      "fusedScore": 87,
      "status": "COMPLETE",
      "explanation": "High risk: suspect linked to known fraud network.",
      "pendingReview": false
    },
    "nextSteps": ["An investigator has been assigned.", "You may upload evidence via the app."]
  }
}
```

**Errors:** `404 CASE_NOT_FOUND` | `403 NOT_YOUR_CASE` — citizens only see their own cases

---

### POST /citizen/bot/message
Send a message to the fraud assessment chatbot.

**BFF orchestration:** Proxies directly to `POST /bot/message` on Bot Service.

**Request/Response:** Same as [bot.md](./bot.md) `POST /bot/message`.

---

### GET /citizen/bot/session/:sessionId
Get current bot session state.

**BFF orchestration:** Proxies to `GET /bot/session/:sessionId`.

**Response:** Same as [bot.md](./bot.md) `GET /bot/session/:sessionId`.

---

### POST /citizen/cases/:caseId/evidence
Upload evidence (image, audio, PDF) for a case.

**BFF orchestration:** Proxies to `POST /cases/:caseId/evidence` on Evidence Service.

**Request/Response:** Same as [evidence.md](./evidence.md) `POST /cases/:caseId/evidence`.

---

### POST /citizen/evidence/:evidenceId/confirm
Confirm evidence upload completion.

**BFF orchestration:** Proxies to `POST /evidence/:evidenceId/confirm`.

**Request/Response:** Same as [evidence.md](./evidence.md).
