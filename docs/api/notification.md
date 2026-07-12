# Notification Service — API Contract
**Service:** `notification` | **Port:** 8000 | **Owner:** Nilkanta | **Task:** T8e
**Internal only** — called by Orchestrator (MHA alert) and Investigator BFF (SSE stream).

> See [_shared_contract.md](./_shared_contract.md) for envelope and health conventions.

---

## MHA Alert Architecture

The MHA alert channel uses a **dedicated Kafka consumer group** (`mha-alert-priority`) with the highest queue priority — separate from the standard citizen notification consumer group. This prevents head-of-line blocking and guarantees the <5s SLO (FR-10.7).

```
Orchestrator → POST /notify/mha-alert (direct HTTP, bypasses standard queue)
  → Dedicated high-priority queue
  → Webhook POST to MHA endpoint (env: MHA_WEBHOOK_URL)
  → Publish MHAAlert.Sent → Audit
```

---

## Endpoints

### POST /notify/send
Send a standard omnichannel notification.

**Request:**
```json
{
  "userId": "user-uuid",
  "channel": "SMS",
  "templateId": "case_assigned",
  "variables": {
    "caseNumber": "CYB-2026-00001",
    "investigatorName": "Inspector Sharma"
  },
  "priority": "NORMAL"
}
```

**Constraints:**
- `channel`: enum `[SMS, EMAIL, PUSH, SSE]`
- `priority`: enum `[NORMAL, HIGH, CRITICAL]`
- CRITICAL priority bypasses standard queue — immediate dispatch
- SMS/Email/Push: **[STUB]** — logs to console in hackathon; wires to Twilio/SendGrid in production

**Response 202:**
```json
{
  "data": {
    "notificationId": "uuid",
    "status": "QUEUED",
    "estimatedDeliveryMs": 500
  }
}
```

**Events published:** `Notification.Requested`

---

### POST /notify/mha-alert
High-priority MHA webhook dispatch. <5s SLO (FR-10.7).

**Request:**
```json
{
  "caseId": "uuid",
  "alertType": "FRAUD_RING_DETECTED",
  "riskTier": "CRITICAL",
  "summary": "Detected fraud ring of 7 nodes; suspect linked to ₹4.2 Cr in fraudulent transactions.",
  "suspects": ["+919876543210", "+919876543211"],
  "jurisdictionId": "JUR_MH_MUMBAI",
  "triggeredBy": "prediction-uuid"
}
```

**Response 200:**
```json
{
  "data": {
    "alertId": "uuid",
    "status": "DISPATCHED",
    "dispatchedAt": "2026-07-11T12:00:03Z",
    "deliveryLatencyMs": 480
  }
}
```

**Implementation:** Directly POSTs JSON payload to `MHA_WEBHOOK_URL` (env variable). In hackathon demo, this URL is a local mock server.

**Events published:** `MHAAlert.Sent` → Audit Service

---

### GET /notify/stream
Server-Sent Events stream for real-time investigator dashboard updates.

**Headers:** `Authorization: Bearer <JWT>` | `Accept: text/event-stream`

**Response:** SSE stream (persistent connection). Events pushed:
```
event: case_updated
data: {"caseId":"uuid","status":"Action_Taken","riskTier":"HIGH"}

event: prediction_completed
data: {"caseId":"uuid","fusedScore":87.5,"riskTier":"HIGH"}

event: hitl_required
data: {"caseId":"uuid","predictionId":"uuid","confidence":0.45}
```

Connection closes after 30min inactivity (Kong gateway timeout). Client reconnects with `Last-Event-ID` header for resumption.

---

### GET /notify/preferences/:userId
Get notification preferences for a user.

**Response 200:**
```json
{
  "data": {
    "userId": "uuid",
    "smsEnabled": true,
    "emailEnabled": true,
    "pushEnabled": false,
    "quietHoursStart": "22:00",
    "quietHoursEnd": "07:00",
    "language": "hi"
  }
}
```

---

### PATCH /notify/preferences/:userId
Update preferences.

**Request:** Partial update — any subset of preference fields.

**Response 200:** Updated preferences object.

---

## Events Consumed

| Event | Action |
|---|---|
| `Prediction.Completed` | Push SSE `prediction_completed` to relevant investigator stream |
| `Case.Assigned` | Push SSE `case_updated` + dispatch SMS/Email to investigator |
| `CallSession.Flagged` | Trigger MHA alert within 5s |
