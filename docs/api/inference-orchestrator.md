# Inference Orchestrator Service — API Contract
**Service:** `inference-orchestrator` | **Port:** 8000 | **Owner:** Diganta | **Task:** T8
**Internal only** — called by Case Service (via Kafka consumer) and by Event Processing Service (synchronous interdiction path).

> See [_shared_contract.md](./_shared_contract.md) for envelope and health conventions.

---

## Data Flow (Anchor and Expand Strategy)

```
Case.Created (Kafka) → Orchestrator
  1. Extract suspectPhone/suspectAccount as anchor
  2. GET /graph/linkages?entityId={anchor} → 2-hop sub-graph JSON
  3. Bundle complaint + sub-graph into unified payload
  4. asyncio.gather → [POST /ml/scam-classify, POST /ml/graph-analyze,
                       POST /ml/counterfeit-detect*, POST /ml/audio-analyze*]
  5. Compute fusedScore = weighted_avg(model_scores, fusion_weights from Redis)
  6. Persist FusedVerdict to PostgreSQL
  7. Publish Prediction.Completed (or Prediction.Failed) → Kafka
  8. PATCH /cases/:id/state (via internal HTTP)
```

*Audio and counterfeit models are only invoked if relevant evidence exists for the case.

---

## FusedVerdict Object (persisted & returned)

```json
{
  "predictionId": "uuid-v4",
  "caseId": "uuid-v4",
  "fusedScore": 87.5,
  "riskTier": "HIGH",
  "confidence": 0.91,
  "status": "COMPLETE",
  "modelBreakdown": [
    {
      "model": "scam-nlp",
      "score": 92,
      "confidence": 0.95,
      "riskTier": "HIGH",
      "signals": ["urgency language", "impersonation detected"],
      "explanation": "Complaint text contains known scam pressure patterns.",
      "modelVersion": "v1.2.0",
      "latencyMs": 145
    },
    {
      "model": "graph-analyzer",
      "score": 83,
      "confidence": 0.88,
      "riskTier": "HIGH",
      "suspiciousNodes": ["+919876543210", "ACC123"],
      "explanation": "Suspect linked to 3 previously flagged fraud nodes.",
      "modelVersion": "v1.0.1",
      "latencyMs": 210
    }
  ],
  "explanation": "Multi-model consensus: NLP detected urgency patterns; graph links to known fraud ring.",
  "fusionWeights": {"scam-nlp": 0.4, "graph-analyzer": 0.35, "audio-analyzer": 0.15, "counterfeit-cv": 0.1},
  "fusionTimestamp": "2026-07-11T12:00:45Z",
  "pendingReview": false
}
```

**riskTier thresholds:**
| Tier | Score Range |
|---|---|
| `LOW` | 0 – 39 |
| `MEDIUM` | 40 – 69 |
| `HIGH` | 70 – 89 |
| `CRITICAL` | 90 – 100 |

**status values:**
- `COMPLETE` — all invoked models responded
- `INCOMPLETE` — ≥1 model timed out; partial results persisted; case routed to `PENDING_REVIEW`
- `PENDING_REVIEW` — confidence < threshold (configurable); automated actions suppressed

---

## Endpoints

### POST /inference/analyze
Trigger multi-source AI fusion analysis for a case. Normally called internally by Kafka consumer, but also callable directly for the synchronous interdiction path (T15).

**Request:**
```json
{
  "caseId": "uuid",
  "triggerType": "CASE_CREATED",
  "complaint": {
    "title": "Suspected UPI fraud",
    "description": "...",
    "complaintType": "UPI_FRAUD",
    "suspectPhone": "+919876543210",
    "suspectAccount": "XXXXXX1234",
    "languageCode": "hi"
  },
  "evidenceRefs": [
    {"evidenceId": "uuid", "mimeType": "audio/wav"}
  ]
}
```

**Constraints:**
- `triggerType`: enum `[CASE_CREATED, EVIDENCE_UPLOADED, TELECOM_EVENT, BANK_TRANSACTION]`
- `evidenceRefs`: optional; determines which ML models are activated

**Response 202:** (async — result published via Kafka)
```json
{
  "data": {
    "predictionId": "uuid",
    "status": "PROCESSING",
    "estimatedCompletionMs": 2000
  }
}
```

**For synchronous interdiction path (T15):** Pass `"sync": true` in request body. Response is synchronous with full `FusedVerdict` object. Max timeout: 300ms (returns `INCOMPLETE` if exceeded).

---

### GET /inference/predictions/:predictionId
Retrieve a stored FusedVerdict by ID.

**Response 200:** Full `FusedVerdict` object (see above).

**Errors:** `404 PREDICTION_NOT_FOUND`

---

### GET /inference/cases/:caseId/latest
Get the most recent prediction for a case.

**Response 200:** Full `FusedVerdict` object or `404 NO_PREDICTION_YET`.

---

## Configuration (Redis keys — hot-reload without restart, FR-14.4)

| Redis Key | Type | Default | Description |
|---|---|---|---|
| `fusion:weights` | Hash | `{"scam-nlp":0.4,"graph-analyzer":0.35,"audio-analyzer":0.15,"counterfeit-cv":0.1}` | Contribution weights |
| `fusion:enabled_models` | Set | `{scam-nlp, graph-analyzer, audio-analyzer, counterfeit-cv}` | Toggle models without deploy |
| `fusion:confidence_threshold` | String | `0.70` | Below this → PENDING_REVIEW |
| `fusion:per_model_timeout_ms` | String | `2000` | Per-model invocation timeout |

---

## Events Published

| Event | Trigger |
|---|---|
| `Prediction.Completed` | Successful COMPLETE or INCOMPLETE verdict |
| `Prediction.Failed` | All models failed / network unreachable |
| `Prediction.Overridden` | Investigator HITL decision recorded |
