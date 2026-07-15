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
async def counterfeit_detect(_: CounterfeitDetectRequest) -> dict[str, Any]:
    start = time.perf_counter()
    return {
        "score": 80,
        "isAuthentic": False,
        "confidence": 0.80,
        "detectedFeatures": {},
        "signals": ["stub"],
        "explanation": "STUB",
        "modelVersion": MODEL_VERSION,
        "processingMs": processing_ms(start),
    }


@app.post("/ml/graph-analyze", tags=["ML"])
async def graph_analyze(_: GraphAnalyzeRequest) -> dict[str, Any]:
    start = time.perf_counter()
    return {
        "score": 70,
        "fraudRingProbability": 0.75,
        "suspiciousNodes": [],
        "ringSize": 1,
        "signals": ["stub"],
        "explanation": "STUB",
        "modelVersion": MODEL_VERSION,
        "processingMs": processing_ms(start),
    }


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
