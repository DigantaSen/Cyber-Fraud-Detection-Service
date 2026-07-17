import base64
import binascii
import json
import os
import re
import time
from enum import Enum
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator


SERVICE_NAME = os.getenv("SERVICE_NAME", "ml-stub")
MODEL_VERSION = os.getenv("MODEL_VERSION", "stub-v0.1")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:latest")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "45"))
SCAM_NLP_PROVIDER = os.getenv("SCAM_NLP_PROVIDER", "ollama").lower()
SCAM_NLP_RULES_VERSION = os.getenv("SCAM_NLP_RULES_VERSION", "rules-v0.1")
COUNTERFEIT_CV_PROVIDER = os.getenv("COUNTERFEIT_CV_PROVIDER", "groq").lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "45"))

SUPPORTED_LANGUAGES = {
    "hi",
    "bn",
    "te",
    "ta",
    "mr",
    "gu",
    "kn",
    "ml",
    "pa",
    "ur",
    "or",
    "as",
    "en",
}
ALLOWED_IMAGE_DENOMINATIONS = {10, 20, 50, 100, 200, 500, 2000}
ALLOWED_AUDIO_MIME_TYPES = {"audio/wav", "audio/mpeg", "audio/m4a", "audio/ogg"}

SCAM_RULES = [
    {
        "name": "urgency pressure language detected",
        "pattern": r"\b(urgent|immediately|right now|now)\b|जल्दी|अभी|तुरंत|फौरन",
        "weight": 18,
    },
    {
        "name": "authority impersonation pattern",
        "pattern": r"\b(police|cbi|rbi|bank officer|customs|income tax|fir|arrest|court)\b|पुलिस|सीबीआई|आरबीआई|गिरफ्तार|एफआईआर",
        "weight": 22,
    },
    {
        "name": "financial transfer pressure",
        "pattern": r"\b(transfer|send money|pay|payment|upi|gpay|phonepe|paytm)\b|पैसे|भुगतान|ट्रांसफर|यूपीआई",
        "weight": 18,
    },
    {
        "name": "credential or OTP request",
        "pattern": r"\b(otp|pin|password|cvv|card number|login|verification code|ओटीपी|पासवर्ड|पिन)\b",
        "weight": 24,
    },
    {
        "name": "threat or coercion detected",
        "pattern": r"\b(block|freeze|legal action|case filed|penalty|fine|jail)\b|बंद|जुर्माना|केस|जेल|धमकी",
        "weight": 16,
    },
    {
        "name": "reward or lottery lure",
        "pattern": r"\b(lottery|winner|prize|reward|cashback|gift|free|लॉटरी|इनाम|पुरस्कार|गिफ्ट)\b",
        "weight": 14,
    },
    {
        "name": "investment return lure",
        "pattern": r"\b(invest|investment|double money|guaranteed return|crypto|trading|profit|निवेश|मुनाफा)\b",
        "weight": 18,
    },
    {
        "name": "relationship trust lure",
        "pattern": r"\b(love|romance|friendship|marriage|dating|emergency help|प्यार|दोस्ती|शादी)\b",
        "weight": 12,
    },
]

CATEGORY_RULES = [
    ("UPI_SCAM", r"\b(upi|gpay|phonepe|paytm|qr|collect request|यूपीआई)\b"),
    ("IMPERSONATION_FRAUD", r"\b(police|cbi|rbi|bank officer|customs|income tax|fir|arrest|पुलिस|सीबीआई|आरबीआई|गिरफ्तार)\b"),
    ("INVESTMENT_FRAUD", r"\b(invest|investment|double money|guaranteed return|crypto|trading|profit|निवेश|मुनाफा)\b"),
    ("LOTTERY_SCAM", r"\b(lottery|winner|prize|reward|cashback|gift|लॉटरी|इनाम|पुरस्कार)\b"),
    ("ROMANCE_SCAM", r"\b(love|romance|friendship|marriage|dating|प्यार|दोस्ती|शादी)\b"),
]


class ComplaintType(str, Enum):
    UPI_FRAUD = "UPI_FRAUD"
    CALL_FRAUD = "CALL_FRAUD"
    COUNTERFEIT_CURRENCY = "COUNTERFEIT_CURRENCY"
    CYBER_CRIME = "CYBER_CRIME"
    OTHER = "OTHER"


class Metadata(BaseModel):
    correlationId: str | None = None
    caseId: str | None = None


class ScamClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    languageCode: str
    complaintType: ComplaintType
    metadata: Metadata | None = None

    @field_validator("languageCode")
    @classmethod
    def language_must_be_supported(cls, value: str) -> str:
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError("languageCode must be one of the supported BCP-47 language codes")
        return value


class ScamClassifyResponse(BaseModel):
    score: int = Field(ge=0, le=100)
    riskTier: str
    category: str
    confidence: float = Field(ge=0, le=1)
    signals: list[str]
    explanation: str
    modelVersion: str

    @field_validator("riskTier")
    @classmethod
    def risk_tier_must_match_contract(cls, value: str) -> str:
        allowed = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        if value not in allowed:
            raise ValueError(f"riskTier must be one of {sorted(allowed)}")
        return value

    @field_validator("category")
    @classmethod
    def category_must_match_contract(cls, value: str) -> str:
        allowed = {
            "IMPERSONATION_FRAUD",
            "UPI_SCAM",
            "INVESTMENT_FRAUD",
            "LOTTERY_SCAM",
            "ROMANCE_SCAM",
            "UNKNOWN",
        }
        if value not in allowed:
            raise ValueError(f"category must be one of {sorted(allowed)}")
        return value


class CounterfeitDetectRequest(BaseModel):
    imageBase64: str
    denomination: int
    metadata: Metadata | None = None

    @field_validator("denomination")
    @classmethod
    def denomination_must_be_supported(cls, value: int) -> int:
        if value not in ALLOWED_IMAGE_DENOMINATIONS:
            raise ValueError("denomination must be a supported INR denomination")
        return value

    @field_validator("imageBase64")
    @classmethod
    def image_must_be_small_base64(cls, value: str) -> str:
        decoded_size = decoded_base64_size(value, max_bytes=5 * 1024 * 1024)
        if decoded_size > 5 * 1024 * 1024:
            raise ValueError("imageBase64 decoded size must not exceed 5MB")
        return value


class CounterfeitDetectedFeatures(BaseModel):
    securityThread: bool | None = None
    watermark: bool | None = None
    microprinting: bool | None = None
    colorShift: bool | None = None
    imageQuality: str | None = None


class CounterfeitDetectResponse(BaseModel):
    score: int = Field(ge=0, le=100)
    isAuthentic: bool
    confidence: float = Field(ge=0, le=1)
    detectedFeatures: CounterfeitDetectedFeatures | dict[str, Any]
    signals: list[str]
    explanation: str
    modelVersion: str


class GraphNode(BaseModel):
    id: str
    type: str
    fraudScore: int | float | None = None


class GraphEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    relation: str
    count: int | None = None


class GraphPayload(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class GraphAnalyzeRequest(BaseModel):
    anchorEntityId: str
    graph: GraphPayload
    metadata: Metadata | None = None


class SuspiciousGraphNode(BaseModel):
    id: str
    fraudScore: int | float
    reason: str


class GraphAnalyzeResponse(BaseModel):
    score: int = Field(ge=0, le=100)
    fraudRingProbability: float = Field(ge=0, le=1)
    suspiciousNodes: list[SuspiciousGraphNode]
    ringSize: int = Field(ge=0)
    signals: list[str]
    explanation: str
    modelVersion: str


class AudioAnalyzeRequest(BaseModel):
    audioBase64: str
    mimeType: str
    durationSeconds: float = Field(ge=0, le=300)
    metadata: Metadata | None = None

    @field_validator("mimeType")
    @classmethod
    def audio_mime_must_be_supported(cls, value: str) -> str:
        if value not in ALLOWED_AUDIO_MIME_TYPES:
            raise ValueError("mimeType must be one of the supported audio formats")
        return value

    @field_validator("audioBase64")
    @classmethod
    def audio_must_be_small_base64(cls, value: str) -> str:
        decoded_size = decoded_base64_size(value, max_bytes=50 * 1024 * 1024)
        if decoded_size > 50 * 1024 * 1024:
            raise ValueError("audioBase64 decoded size must not exceed 50MB")
        return value


def decoded_base64_size(value: str, max_bytes: int) -> int:
    if value.startswith("data:"):
        _, _, value = value.partition(",")

    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("value must be valid base64") from exc

    size = len(decoded)
    if size > max_bytes:
        raise ValueError("decoded base64 payload is too large")
    return size


def processing_ms(start: float) -> int:
    return max(10, round((time.perf_counter() - start) * 1000))


def risk_tier(score: int) -> str:
    if score >= 90:
        return "CRITICAL"
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def classify_scam_text(request: ScamClassifyRequest) -> dict[str, Any]:
    text = request.text.lower()
    signals = []
    score = 10

    for rule in SCAM_RULES:
        if re.search(rule["pattern"], text, flags=re.IGNORECASE):
            signals.append(rule["name"])
            score += rule["weight"]

    if request.complaintType == ComplaintType.UPI_FRAUD:
        score += 8
    elif request.complaintType == ComplaintType.CALL_FRAUD:
        score += 6
    elif request.complaintType == ComplaintType.CYBER_CRIME:
        score += 5

    if re.search(r"(₹|rs\.?|inr)\s?\d+|\d+\s?(rupees|रुपये)", text, flags=re.IGNORECASE):
        signals.append("explicit money amount mentioned")
        score += 8

    if not signals:
        signals.append("no strong scam pattern detected")

    category = "UNKNOWN"
    for candidate, pattern in CATEGORY_RULES:
        if re.search(pattern, text, flags=re.IGNORECASE):
            category = candidate
            break

    score = min(score, 100)
    confidence = min(0.95, 0.45 + (len(signals) * 0.08) + (score / 250))

    return {
        "score": score,
        "riskTier": risk_tier(score),
        "category": category,
        "confidence": round(confidence, 2),
        "signals": signals[:5],
        "explanation": build_scam_explanation(score, category, signals, request.languageCode),
        "modelVersion": SCAM_NLP_RULES_VERSION,
    }


def classify_scam_text_safely(request: ScamClassifyRequest) -> dict[str, Any]:
    if SCAM_NLP_PROVIDER == "ollama":
        try:
            return classify_scam_text_with_ollama(request)
        except Exception as exc:
            response = classify_scam_text(request)
            response["modelVersion"] = "rules-fallback-v0.1"
            response["signals"] = [*response["signals"][:4], f"ollama unavailable: {type(exc).__name__}"]
            response["explanation"] = f"{response['explanation']} Ollama unavailable; used local fallback."
            return response

    return classify_scam_text(request)


def classify_scam_text_with_ollama(request: ScamClassifyRequest) -> dict[str, Any]:
    prompt = build_ollama_scam_prompt(request)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_predict": 350,
        },
    }

    with httpx.Client(timeout=OLLAMA_TIMEOUT_SECONDS) as client:
        response = client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
        response.raise_for_status()

    raw_text = response.json()["response"]
    parsed = json.loads(raw_text)
    parsed["score"] = int(parsed["score"])
    parsed["riskTier"] = risk_tier(parsed["score"])
    parsed["confidence"] = float(parsed["confidence"])
    parsed["signals"] = [str(signal) for signal in parsed.get("signals", [])][:5]
    parsed["modelVersion"] = f"ollama:{OLLAMA_MODEL}"

    contract_response = ScamClassifyResponse.model_validate(parsed)
    return contract_response.model_dump()


def build_ollama_scam_prompt(request: ScamClassifyRequest) -> str:
    return f"""
You are a cyber fraud text classifier for Indian digital safety reports.
Classify the complaint and return ONLY valid JSON. No markdown. No prose outside JSON.

Allowed riskTier values: LOW, MEDIUM, HIGH, CRITICAL.
Allowed category values: IMPERSONATION_FRAUD, UPI_SCAM, INVESTMENT_FRAUD, LOTTERY_SCAM, ROMANCE_SCAM, UNKNOWN.

Scoring guidance:
- 0-39 LOW: normal/unclear text or weak scam evidence.
- 40-69 MEDIUM: suspicious but incomplete evidence.
- 70-89 HIGH: clear scam indicators.
- 90-100 CRITICAL: active threat, coercion, credential theft, or large financial loss.

Return this exact JSON schema:
{{
  "score": 0,
  "riskTier": "LOW",
  "category": "UNKNOWN",
  "confidence": 0.0,
  "signals": ["short evidence signal"],
  "explanation": "one short explanation",
  "modelVersion": "ollama-placeholder"
}}

Complaint metadata:
- languageCode: {request.languageCode}
- complaintType: {request.complaintType.value}

Complaint text:
{request.text}
""".strip()


def build_scam_explanation(score: int, category: str, signals: list[str], language_code: str) -> str:
    if signals == ["no strong scam pattern detected"]:
        return f"Low signal text: no major scam indicators were found. Language: {language_code}."

    signal_text = "; ".join(signals[:3])
    return (
        f"Rule-based scam analysis found {signal_text}. "
        f"Predicted category: {category}. Score: {score}. Language: {language_code}."
    )


def detect_image_mime(image_base64: str) -> str:
    image_bytes = decode_base64_payload(image_base64)
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return "image/jpeg"


def decode_base64_payload(value: str) -> bytes:
    if value.startswith("data:"):
        _, _, value = value.partition(",")
    return base64.b64decode(value, validate=True)


def counterfeit_stub_response(reason: str | None = None) -> dict[str, Any]:
    signals = ["stub"]
    explanation = "STUB"
    model_version = MODEL_VERSION
    if reason:
        signals = [reason, "stub fallback"]
        explanation = f"Groq vision unavailable; returned deterministic fallback. Reason: {reason}."
        model_version = "stub-fallback-v0.1"

    return {
        "score": 80,
        "isAuthentic": False,
        "confidence": 0.80,
        "detectedFeatures": {},
        "signals": signals,
        "explanation": explanation,
        "modelVersion": model_version,
    }


def analyze_counterfeit_safely(request: CounterfeitDetectRequest) -> dict[str, Any]:
    if COUNTERFEIT_CV_PROVIDER == "groq":
        try:
            return analyze_counterfeit_with_groq(request)
        except Exception as exc:
            return counterfeit_stub_response(f"groq unavailable: {type(exc).__name__}")

    return counterfeit_stub_response()


def analyze_counterfeit_with_groq(request: CounterfeitDetectRequest) -> dict[str, Any]:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    image_mime = detect_image_mime(request.imageBase64)
    image_payload = request.imageBase64.partition(",")[2] if request.imageBase64.startswith("data:") else request.imageBase64
    prompt = build_groq_counterfeit_prompt(request.denomination)
    payload = {
        "model": GROQ_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_mime};base64,{image_payload}",
                        },
                    },
                ],
            }
        ],
        "temperature": 0,
        "max_completion_tokens": 600,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=GROQ_TIMEOUT_SECONDS) as client:
        response = client.post(f"{GROQ_BASE_URL}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()

    raw_content = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(raw_content)
    parsed["score"] = int(parsed["score"])
    parsed["confidence"] = float(parsed["confidence"])
    parsed["isAuthentic"] = bool(parsed["isAuthentic"])
    parsed["signals"] = [str(signal) for signal in parsed.get("signals", [])][:5]
    parsed["modelVersion"] = f"groq:{GROQ_VISION_MODEL}"

    contract_response = CounterfeitDetectResponse.model_validate(parsed)
    return contract_response.model_dump()


def build_groq_counterfeit_prompt(denomination: int) -> str:
    return f"""
You are a counterfeit Indian currency image inspection model.
Inspect the provided currency note image for denomination INR {denomination}.
Return ONLY valid JSON. No markdown. No prose outside JSON.

This is a demo risk assessment, not a legal authenticity certificate.

Look for visible evidence such as:
- security thread presence/absence
- watermark visibility
- microprinting or fine detail clarity
- color-shift/security ink cues when visible
- poor print quality, blur, low contrast, or suspicious artifacts
- denomination mismatch or missing note-like features

Return this exact JSON schema:
{{
  "score": 0,
  "isAuthentic": true,
  "confidence": 0.0,
  "detectedFeatures": {{
    "securityThread": null,
    "watermark": null,
    "microprinting": null,
    "colorShift": null,
    "imageQuality": "clear|blurry|low_light|partial|unknown"
  }},
  "signals": ["short visual evidence signal"],
  "explanation": "one short explanation",
  "modelVersion": "groq-placeholder"
}}

Scoring guidance:
- score means counterfeit/suspicion score, where 0 is likely authentic and 100 is highly suspicious.
- isAuthentic should be false when score >= 50.
- confidence should reflect visual certainty from 0.0 to 1.0.
""".strip()


def analyze_graph_features(request: GraphAnalyzeRequest) -> dict[str, Any]:
    nodes = request.graph.nodes
    edges = request.graph.edges
    node_by_id = {node.id: node for node in nodes}
    degree = {node.id: 0 for node in nodes}
    repeated_relation_count = 0
    relation_pair_counts: dict[tuple[str, str, str], int] = {}

    for edge in edges:
        if edge.from_ in degree:
            degree[edge.from_] += 1
        if edge.to in degree:
            degree[edge.to] += 1

        key = tuple(sorted([edge.from_, edge.to]) + [edge.relation])
        relation_pair_counts[key] = relation_pair_counts.get(key, 0) + (edge.count or 1)
        if edge.count and edge.count >= 5:
            repeated_relation_count += 1

    high_risk_nodes = [
        node for node in nodes
        if node.fraudScore is not None and float(node.fraudScore) >= 70
    ]
    hub_nodes = [
        node for node in nodes
        if degree.get(node.id, 0) >= 3
    ]
    anchor_degree = degree.get(request.anchorEntityId, 0)
    node_count = len(nodes)
    edge_count = len(edges)
    possible_edges = max(1, node_count * (node_count - 1) / 2)
    density = min(1.0, edge_count / possible_edges)

    score = 10
    score += min(35, len(high_risk_nodes) * 12)
    score += min(20, len(hub_nodes) * 8)
    score += min(15, anchor_degree * 4)
    score += min(15, round(density * 25))
    score += min(10, repeated_relation_count * 5)
    score = min(100, score)

    suspicious_nodes = []
    seen = set()
    for node in sorted(high_risk_nodes, key=lambda item: float(item.fraudScore or 0), reverse=True):
        suspicious_nodes.append({
            "id": node.id,
            "fraudScore": node.fraudScore or 0,
            "reason": "High prior fraud score in graph neighborhood",
        })
        seen.add(node.id)

    for node in sorted(hub_nodes, key=lambda item: degree.get(item.id, 0), reverse=True):
        if node.id in seen:
            continue
        suspicious_nodes.append({
            "id": node.id,
            "fraudScore": node.fraudScore or 0,
            "reason": f"Hub node with {degree.get(node.id, 0)} graph connections",
        })
        seen.add(node.id)

    signals = []
    if high_risk_nodes:
        signals.append(f"{len(high_risk_nodes)} high-risk node(s) with fraudScore >= 70")
    if hub_nodes:
        signals.append(f"{len(hub_nodes)} hub node(s) with 3+ connections")
    if anchor_degree:
        signals.append(f"anchor entity has {anchor_degree} direct connection(s)")
    if density >= 0.35 and node_count >= 3:
        signals.append(f"dense graph neighborhood detected (density={density:.2f})")
    if repeated_relation_count:
        signals.append(f"{repeated_relation_count} repeated relation(s) with count >= 5")
    if not signals:
        signals.append("no strong graph fraud pattern detected")

    ring_size = len({node["id"] for node in suspicious_nodes})
    if request.anchorEntityId in node_by_id and anchor_degree >= 2:
        ring_size = max(ring_size, min(node_count, anchor_degree + 1))

    explanation = (
        f"Graph analysis found {len(high_risk_nodes)} high-risk nodes, "
        f"{len(hub_nodes)} hubs, anchor degree {anchor_degree}, and density {density:.2f}."
    )

    response = {
        "score": score,
        "fraudRingProbability": round(score / 100, 2),
        "suspiciousNodes": suspicious_nodes[:10],
        "ringSize": ring_size,
        "signals": signals[:5],
        "explanation": explanation,
        "modelVersion": "graph-features-v0.1",
    }
    return GraphAnalyzeResponse.model_validate(response).model_dump()


app = FastAPI(
    title=SERVICE_NAME,
    version=MODEL_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.get("/health/live", tags=["Health"])
async def liveness() -> dict[str, str]:
    return {"status": "alive", "service": SERVICE_NAME, "modelVersion": MODEL_VERSION}


@app.get("/health/ready", tags=["Health"])
async def readiness() -> dict[str, Any]:
    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "modelVersion": MODEL_VERSION,
        "checks": {"model": "stub_loaded"},
    }


@app.post("/ml/scam-classify", tags=["ML"])
async def scam_classify(request: ScamClassifyRequest) -> dict[str, Any]:
    start = time.perf_counter()
    response = classify_scam_text_safely(request)
    response["processingMs"] = processing_ms(start)
    return response


@app.post("/ml/counterfeit-detect", tags=["ML"])
async def counterfeit_detect(request: CounterfeitDetectRequest) -> dict[str, Any]:
    start = time.perf_counter()
    response = analyze_counterfeit_safely(request)
    response["processingMs"] = processing_ms(start)
    return response


@app.post("/ml/graph-analyze", tags=["ML"])
async def graph_analyze(request: GraphAnalyzeRequest) -> dict[str, Any]:
    start = time.perf_counter()
    response = analyze_graph_features(request)
    response["processingMs"] = processing_ms(start)
    return response


@app.post("/ml/audio-analyze", tags=["ML"])
async def audio_analyze(_: AudioAnalyzeRequest) -> dict[str, Any]:
    start = time.perf_counter()
    return {
        "score": 65,
        "isAISpoofed": True,
        "confidence": 0.70,
        "voiceFeatures": {"pitchVariance": 0.02, "spectralEntropy": 3.4},
        "signals": ["stub"],
        "explanation": "STUB",
        "modelVersion": MODEL_VERSION,
        "processingMs": processing_ms(start),
    }
