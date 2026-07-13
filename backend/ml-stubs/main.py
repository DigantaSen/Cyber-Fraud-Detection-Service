import base64
import binascii
import os
import time
from enum import Enum
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator


SERVICE_NAME = os.getenv("SERVICE_NAME", "ml-stub")
MODEL_VERSION = os.getenv("MODEL_VERSION", "stub-v0.1")

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
async def scam_classify(_: ScamClassifyRequest) -> dict[str, Any]:
    start = time.perf_counter()
    return {
        "score": 75,
        "riskTier": "HIGH",
        "category": "IMPERSONATION_FRAUD",
        "confidence": 0.85,
        "signals": ["stub signal"],
        "explanation": "STUB response",
        "modelVersion": MODEL_VERSION,
        "processingMs": processing_ms(start),
    }


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
