# Conversational Bot Service — API Contract
**Service:** `bot` | **Port:** 8000 | **Owner:** Surjit | **Task:** T5b
**Internal only** — called by Citizen BFF only.

> See [_shared_contract.md](./_shared_contract.md) for envelope and health conventions.

---

## Architecture

The Bot service is a **purely synchronous REST service**. It does NOT consume Kafka events.

```
Citizen BFF → POST /bot/message → Bot Service
  → Reads session state from Redis (TTL 30m)
  → Proxies NLP to Inference Orchestrator: POST /inference/analyze
  → Returns response in detected language
  → Updates session in Redis
```

**Language support (FR-11.1):** 12 Indian regional languages + English.
- Detection: `langdetect` library
- Language tag forwarded in Orchestrator request as `languageCode` field
- Orchestrator forwards to NLP model which returns language-appropriate response

**Redis session key pattern:** `bot:session:{sessionId}:lang={lang_code}` — TTL 30 minutes.

---

## Endpoints

### POST /bot/message
Process a citizen message in an ongoing or new bot session.

**Request:**
```json
{
  "sessionId": "uuid (optional — omit for new session)",
  "message": "मुझे एक संदिग्ध UPI अनुरोध मिला",
  "channel": "WEB",
  "userId": "user-uuid (optional for anonymous)"
}
```

**Constraints:**
- `channel`: enum `[WEB, WHATSAPP, IVR]`
  - `WEB`: fully implemented
  - `WHATSAPP`: **[STUB]** — echoes structured ack (FR-11.4)
  - `IVR`: **[STUB]** — not built for hackathon (FR-11.5)
- `message`: max 2000 chars
- `sessionId`: if omitted, server creates a new one

**Response 200:**
```json
{
  "data": {
    "sessionId": "uuid-v4",
    "response": "आपकी रिपोर्ट दर्ज हो गई है। कृपया संदिग्ध नंबर प्रदान करें।",
    "detectedLanguage": "hi",
    "intent": "FRAUD_REPORT_INITIATION",
    "riskAssessment": {
      "preliminaryScore": 72,
      "riskTier": "HIGH",
      "requiresFormatReport": true
    },
    "suggestedActions": ["SUBMIT_FORMAL_REPORT", "PROVIDE_SCREENSHOT"],
    "turnCount": 2,
    "sessionExpiresAt": "2026-07-11T12:30:00Z"
  }
}
```

**Notes:**
- `riskAssessment` is populated after ≥2 turns when enough context is gathered and Orchestrator returns a score
- Before Orchestrator integration (T13), returns `null` for `riskAssessment` — pre-wired stub

---

### GET /bot/session/:sessionId
Retrieve the current state of a bot session.

**Response 200:**
```json
{
  "data": {
    "sessionId": "uuid",
    "turnCount": 5,
    "detectedLanguage": "hi",
    "collectedData": {
      "suspectPhone": "+919876543210",
      "complaintType": "UPI_FRAUD",
      "description": "..."
    },
    "status": "ACTIVE",
    "expiresAt": "2026-07-11T12:30:00Z"
  }
}
```

**Errors:** `404 SESSION_NOT_FOUND` — expired or invalid session

---

### POST /bot/whatsapp
WhatsApp Business API webhook endpoint. **[STUB]**

**Request:** Standard Meta WhatsApp webhook payload (JSON).

**Response 200:**
```json
{
  "data": {
    "acknowledged": true,
    "message": "Report received. A case officer will contact you shortly."
  }
}
```

Implementation note: In production, this endpoint normalizes the WhatsApp payload into the standard `/bot/message` format and routes it through the same session pipeline.
