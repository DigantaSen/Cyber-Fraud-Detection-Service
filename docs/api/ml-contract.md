# ML Contract — All 4 AI Model APIs + Fusion Contract
**Owner:** Kushal (model APIs) + Diganta (fusion integration)
**Task:** T10a (Scam NLP), T10b (Counterfeit CV), T10c (Graph Analyzer), T10d (Audio Analyzer)

> This document defines the API contracts that Kushal's ML services must implement. The Inference Orchestrator calls these endpoints. Any deviation from these contracts requires team-wide approval.

---

## Common Rules for ALL ML APIs

1. **Base URL:** Each ML service runs on its own port (see below). Not exposed at Kong — internal only.
2. **No JWT required** — services are on the internal Docker bridge network only.
3. **Timeout:** Orchestrator sends each request with a 2-second timeout. If no response, verdict is `INCOMPLETE` for that model.
4. **Health:** Every ML service must implement `GET /health/live` and `GET /health/ready`.
5. **Stub requirement (Day 2-3):** Stub must be live and return hardcoded valid responses matching the schema below. Integration (T13) starts Day 6 against real models.

---

## Scam NLP Classifier — `POST /ml/scam-classify`
**Service:** `ml/scam-nlp` | **Port:** 8100 | **Owner:** Kushal | **Stub due:** Day 2 EOD

**Request:**
```json
{
  "text": "मुझे अभी ₹50,000 ट्रांसफर करो नहीं तो FIR होगी",
  "languageCode": "hi",
  "complaintType": "UPI_FRAUD",
  "metadata": {
    "correlationId": "uuid",
    "caseId": "uuid"
  }
}
```

**Constraints:**
- `text`: max 5000 chars
- `languageCode`: BCP-47 code — one of the 12 supported languages or `en`
- `complaintType`: enum `[UPI_FRAUD, CALL_FRAUD, COUNTERFEIT_CURRENCY, CYBER_CRIME, OTHER]`

**Response 200:**
```json
{
  "score": 92,
  "riskTier": "HIGH",
  "category": "IMPERSONATION_FRAUD",
  "confidence": 0.95,
  "signals": [
    "urgency pressure language detected",
    "authority impersonation pattern",
    "financial coercion"
  ],
  "explanation": "Text contains high-severity urgency patterns with authority impersonation. Language: Hindi.",
  "modelVersion": "v1.2.0",
  "processingMs": 145
}
```

**Category enum:** `[IMPERSONATION_FRAUD, UPI_SCAM, INVESTMENT_FRAUD, LOTTERY_SCAM, ROMANCE_SCAM, UNKNOWN]`

**Stub response (hardcoded until real model ready):**
```json
{"score": 75, "riskTier": "HIGH", "category": "IMPERSONATION_FRAUD", "confidence": 0.85, "signals": ["stub signal"], "explanation": "STUB response", "modelVersion": "stub-v0.1", "processingMs": 10}
```

---

## Counterfeit Currency Detector — `POST /ml/counterfeit-detect`
**Service:** `ml/counterfeit-cv` | **Port:** 8101 | **Owner:** Kushal | **Stub due:** Day 3

**Request:**
```json
{
  "imageBase64": "<base64-encoded image>",
  "denomination": 500,
  "metadata": {"correlationId": "uuid", "caseId": "uuid"}
}
```

**Constraints:**
- `imageBase64`: JPEG or PNG, max 5MB when decoded
- `denomination`: integer INR denomination `[10, 20, 50, 100, 200, 500, 2000]`

**Response 200:**
```json
{
  "score": 88,
  "isAuthentic": false,
  "confidence": 0.91,
  "detectedFeatures": {
    "securityThread": false,
    "watermark": true,
    "microprinting": false,
    "colorShift": false
  },
  "signals": ["missing security thread", "microprinting absent"],
  "explanation": "Security thread and microprinting absent. High probability of counterfeit ₹500 note.",
  "modelVersion": "v1.0.0",
  "processingMs": 320
}
```

**Stub:** `{"score": 80, "isAuthentic": false, "confidence": 0.80, "detectedFeatures": {}, "signals": ["stub"], "explanation": "STUB", "modelVersion": "stub-v0.1", "processingMs": 10}`

---

## Fraud Graph Analyzer — `POST /ml/graph-analyze`
**Service:** `ml/graph-analyzer` | **Port:** 8102 | **Owner:** Kushal | **Stub due:** Day 3

**Request:**
```json
{
  "anchorEntityId": "+919876543210",
  "graph": {
    "nodes": [
      {"id": "+919876543210", "type": "PHONE", "fraudScore": 87},
      {"id": "+919876543211", "type": "PHONE", "fraudScore": 92}
    ],
    "edges": [
      {"from": "+919876543210", "to": "+919876543211", "relation": "CALLED", "count": 47}
    ]
  },
  "metadata": {"correlationId": "uuid", "caseId": "uuid"}
}
```

**Response 200:**
```json
{
  "score": 83,
  "fraudRingProbability": 0.88,
  "suspiciousNodes": [
    {"id": "+919876543211", "fraudScore": 92, "reason": "Hub node with 7+ connections to HIGH-risk accounts"}
  ],
  "ringSize": 3,
  "signals": ["dense subgraph matching known mule pattern", "cycle detected in 2-hop neighborhood"],
  "explanation": "Graph topology matches money-mule fraud ring pattern. Anchor connected to 2 previously convicted fraud nodes.",
  "modelVersion": "v1.0.1",
  "processingMs": 210
}
```

**Stub:** `{"score": 70, "fraudRingProbability": 0.75, "suspiciousNodes": [], "ringSize": 1, "signals": ["stub"], "explanation": "STUB", "modelVersion": "stub-v0.1", "processingMs": 10}`

---

## Audio Voice Spoof Analyzer — `POST /ml/audio-analyze`
**Service:** `ml/audio-analyzer` | **Port:** 8103 | **Owner:** Kushal | **Stub due:** Day 3

**Request:**
```json
{
  "audioBase64": "<base64-encoded audio>",
  "mimeType": "audio/wav",
  "durationSeconds": 12.5,
  "metadata": {"correlationId": "uuid", "caseId": "uuid"}
}
```

**Constraints:**
- `mimeType`: `audio/wav`, `audio/mpeg`, `audio/m4a`, `audio/ogg`
- `durationSeconds`: max 300 (5 minutes)
- Audio file max decoded size: 50MB

**Response 200:**
```json
{
  "score": 79,
  "isAISpoofed": true,
  "confidence": 0.83,
  "voiceFeatures": {
    "pitchVariance": 0.02,
    "spectralEntropy": 3.4,
    "melFrequencyCepstral": [...]
  },
  "signals": ["abnormally low pitch variance (synthetic voice indicator)", "spectral entropy below human baseline"],
  "explanation": "Voice exhibits characteristics consistent with TTS synthesis. Pitch variance significantly below human baseline.",
  "modelVersion": "v1.1.0",
  "processingMs": 580
}
```

**Stub:** `{"score": 65, "isAISpoofed": true, "confidence": 0.70, "voiceFeatures": {"pitchVariance": 0.02, "spectralEntropy": 3.4}, "signals": ["stub"], "explanation": "STUB", "modelVersion": "stub-v0.1", "processingMs": 10}`

---

## Fusion Contract (Orchestrator → Kafka)

The Orchestrator publishes this exact event on Kafka `prediction-events` topic:

```json
{
  "eventType": "Prediction.Completed",
  "predictionId": "uuid",
  "caseId": "uuid",
  "fusedScore": 87.5,
  "riskTier": "HIGH",
  "confidence": 0.91,
  "status": "COMPLETE",
  "modelBreakdown": [ ... ],
  "explanation": "...",
  "fusionWeights": { ... },
  "fusionTimestamp": "2026-07-11T12:00:45Z",
  "pendingReview": false,
  "correlationId": "uuid"
}
```
