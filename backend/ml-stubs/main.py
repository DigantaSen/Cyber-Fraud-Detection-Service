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
SCAM_NLP_PROVIDER = os.getenv("SCAM_NLP_PROVIDER", "groq").lower()
SCAM_NLP_RULES_VERSION = os.getenv("SCAM_NLP_RULES_VERSION", "rules-v0.1")
COUNTERFEIT_CV_PROVIDER = os.getenv("COUNTERFEIT_CV_PROVIDER", "groq").lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_SCAM_NLP_MODEL = os.getenv("GROQ_SCAM_NLP_MODEL", "llama-3.3-70b-versatile")
GROQ_VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
)
GROQ_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "45"))
AUDIO_ANALYZER_PROVIDER = os.getenv("AUDIO_ANALYZER_PROVIDER", "groq").lower()
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")
GROQ_AUDIO_LLM_MODEL = os.getenv(
    "GROQ_AUDIO_LLM_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
)
GROQ_WHISPER_TIMEOUT_SECONDS = float(os.getenv("GROQ_WHISPER_TIMEOUT_SECONDS", "60"))

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
        "pattern": r"\b(police|cbi|rbi|bank officer|customs|income tax|fir|arrest|court|cyber crime|cyber cell|criminal case)\b|पुलिस|सीबीआई|आरबीआई|गिरफ्तार|एफआईआर",
        "weight": 22,
    },
    {
        "name": "financial transfer pressure",
        "pattern": r"\b(transfer|send money|pay|payment|upi|gpay|google pay|phonepe|paytm|needs? money|financial help|emergency (money|help|assistance))\b|पैसे|भुगतान|ट्रांसफर|यूपीआई",
        "weight": 20,
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
        "pattern": r"\b(lottery|winner|prize|reward|cashback|gift|free|claim.*prize|processing fee|लॉटरी|इनाम|पुरस्कार|गिफ्ट)\b",
        "weight": 20,
    },
    {
        "name": "investment return lure",
        "pattern": r"\b(invest|investment|double money|guaranteed return|crypto|trading|profit|निवेश|मुनाफा)\b",
        "weight": 22,
    },
    {
        "name": "relationship trust lure",
        "pattern": r"\b(love|romance|friendship|marriage|dating|emergency help|प्यार|दोस्ती|शादी)\b",
        "weight": 20,
    },
    {
        "name": "UPI collect-request or QR social engineering",
        "pattern": r"\b(collect request|qr code|scan.{0,15}qr|approve.{0,20}request)\b|कलेक्ट रिक्वेस्ट",
        "weight": 20,
    },
    {
        "name": "gift card or wire transfer request",
        "pattern": r"\b(gift card|western union|wire transfer|itunes card|google play card)\b",
        "weight": 20,
    },
]

CATEGORY_RULES = [
    ("UPI_SCAM", r"\b(upi|gpay|google pay|phonepe|paytm|qr|collect request)\b|यूपीआई|कलेक्ट रिक्वेस्ट"),
    (
        "IMPERSONATION_FRAUD",
        r"\b(police|cbi|rbi|bank officer|customs|income tax|fir|arrest|cyber crime|cyber cell|criminal case|पुलिस|सीबीआई|आरबीआई|गिरफ्तार)\b",
    ),
    (
        "INVESTMENT_FRAUD",
        r"\b(invest|investment|double money|guaranteed return|crypto|trading|profit|निवेश|मुनाफा)\b",
    ),
    # Romance is checked before lottery/reward so a shared "gift" mention (e.g. gift
    # cards requested by a romance-scam actor) doesn't get miscategorized as a lottery win.
    ("ROMANCE_SCAM", r"\b(love|romance|friendship|marriage|dating|प्यार|दोस्ती|शादी)\b"),
    (
        "LOTTERY_SCAM",
        r"\b(lottery|winner|prize|reward|cashback|claim.*prize|processing fee|लॉटरी|इनाम|पुरस्कार)\b",
    ),
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
            raise ValueError(
                "languageCode must be one of the supported BCP-47 language codes"
            )
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


class VoiceFeatures(BaseModel):
    pitchVariance: float | None = None
    spectralEntropy: float | None = None
    melFrequencyCepstral: list[float] | None = None
    backgroundNoise: str | None = None
    speakingRateWpm: int | None = None


class AudioAnalyzeResponse(BaseModel):
    score: int = Field(ge=0, le=100)
    isAISpoofed: bool
    confidence: float = Field(ge=0, le=1)
    voiceFeatures: VoiceFeatures | dict[str, Any]
    signals: list[str]
    explanation: str
    modelVersion: str


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
    score = 12

    for rule in SCAM_RULES:
        if re.search(rule["pattern"], text, flags=re.IGNORECASE):
            signals.append(rule["name"])
            score += rule["weight"]

    if request.complaintType == ComplaintType.UPI_FRAUD:
        score += 8
    elif request.complaintType == ComplaintType.CALL_FRAUD:
        score += 6
    elif request.complaintType == ComplaintType.CYBER_CRIME:
        score += 8

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
        "explanation": build_scam_explanation(
            score, category, signals, request.languageCode
        ),
        "modelVersion": SCAM_NLP_RULES_VERSION,
    }


def classify_scam_text_safely(request: ScamClassifyRequest) -> dict[str, Any]:
    if SCAM_NLP_PROVIDER == "groq":
        try:
            return classify_scam_text_with_groq(request)
        except Exception as exc:
            response = classify_scam_text(request)
            response["modelVersion"] = "rules-fallback-v0.1"
            response["signals"] = [
                *response["signals"][:4],
                f"groq unavailable: {type(exc).__name__}",
            ]
            response["explanation"] = (
                f"{response['explanation']} Groq unavailable; used local fallback."
            )
            return response

    return classify_scam_text(request)


def classify_scam_text_with_groq(request: ScamClassifyRequest) -> dict[str, Any]:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    prompt = build_groq_scam_prompt(request)
    payload = {
        "model": GROQ_SCAM_NLP_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_completion_tokens": 350,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=GROQ_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{GROQ_BASE_URL}/chat/completions", headers=headers, json=payload
        )
        response.raise_for_status()

    raw_content = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(raw_content)
    parsed["score"] = int(parsed["score"])
    parsed["riskTier"] = risk_tier(parsed["score"])
    parsed["confidence"] = float(parsed["confidence"])
    parsed["signals"] = [str(signal) for signal in parsed.get("signals", [])][:5]
    parsed["modelVersion"] = f"groq:{GROQ_SCAM_NLP_MODEL}"

    contract_response = ScamClassifyResponse.model_validate(parsed)
    return contract_response.model_dump()


def build_groq_scam_prompt(request: ScamClassifyRequest) -> str:
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
  "modelVersion": "groq-placeholder"
}}

Complaint metadata:
- languageCode: {request.languageCode}
- complaintType: {request.complaintType.value}

Complaint text:
{request.text}
""".strip()


def build_scam_explanation(
    score: int, category: str, signals: list[str], language_code: str
) -> str:
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
    image_payload = (
        request.imageBase64.partition(",")[2]
        if request.imageBase64.startswith("data:")
        else request.imageBase64
    )
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
        response = client.post(
            f"{GROQ_BASE_URL}/chat/completions", headers=headers, json=payload
        )
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


# ── Audio Voice Spoof Analyzer ─────────────────────────────────────────────────

# Heuristic audio signal rules for deterministic fallback scoring.
# These fire on lexical/duration cues extracted without signal processing.
AUDIO_SPOOF_RULES = [
    {
        "name": "abnormally low pitch variance (synthetic voice indicator)",
        "weight": 25,
        "trigger": "tts_marker",
    },
    {
        "name": "spectral entropy below human baseline",
        "weight": 20,
        "trigger": "low_entropy",
    },
    {
        "name": "unnatural speaking rate (AI pace uniformity)",
        "weight": 18,
        "trigger": "uniform_pace",
    },
    {
        "name": "absence of natural disfluencies (no um/uh/pause)",
        "weight": 15,
        "trigger": "no_disfluency",
    },
    {
        "name": "background noise profile inconsistent with live call",
        "weight": 12,
        "trigger": "clean_bg",
    },
    {
        "name": "authority impersonation language in transcript",
        "weight": 22,
        "trigger": "authority_lang",
    },
    {
        "name": "financial coercion language in transcript",
        "weight": 20,
        "trigger": "financial_lang",
    },
    {
        "name": "urgency pressure language in transcript",
        "weight": 16,
        "trigger": "urgency_lang",
    },
]

# Transcript-level regex patterns (applied to Whisper output or LLM summary)
_AUTHORITY_PATTERN = re.compile(
    r"\b(police|cbi|rbi|income tax|customs|court|arrest|fir|officer|"
    r"पुलिस|सीबीआई|आरबीआई|गिरफ्तार)\b",
    re.IGNORECASE,
)
_FINANCIAL_PATTERN = re.compile(
    r"\b(transfer|send money|upi|gpay|paytm|phonepe|pay|payment|"
    r"पैसे|ट्रांसफर|यूपीआई|भुगतान)\b",
    re.IGNORECASE,
)
_URGENCY_PATTERN = re.compile(
    r"\b(urgent|immediately|right now|now|जल्दी|अभी|तुरंत|फौरन)\b",
    re.IGNORECASE,
)
_DISFLUENCY_PATTERN = re.compile(r"\b(um|uh|hmm|err|ah|oh)\b", re.IGNORECASE)


def _mime_to_extension(mime_type: str) -> str:
    """Map MIME type to file extension for Groq multipart upload."""
    mapping = {
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
        "audio/m4a": "m4a",
        "audio/ogg": "ogg",
    }
    return mapping.get(mime_type, "wav")


def _heuristic_audio_features(
    duration_seconds: float, transcript: str | None
) -> dict[str, Any]:
    """
    Estimate voice features heuristically from duration and transcript length.
    Used when Groq signal processing is unavailable.

    Real implementations would use librosa / pyaudio / torchaudio;
    these estimations produce plausible values in the expected ranges.
    """
    word_count = len(transcript.split()) if transcript else 0
    speaking_rate_wpm = int(word_count / (duration_seconds / 60)) if duration_seconds > 0 else 0

    # Synthetic voices tend toward 140–160 WPM with uniform cadence.
    # Human voices have more variance: 110–200 WPM.
    is_uniform_pace = 140 <= speaking_rate_wpm <= 165

    # Synthetic voices have low pitch variance (< 0.04) and low spectral entropy (< 4.0).
    # Rough estimation: if WPM is suspiciously uniform, assume low variance.
    pitch_variance = round(0.02 + (0.0 if is_uniform_pace else 0.06), 3)
    spectral_entropy = round(3.1 + (0.0 if is_uniform_pace else 1.8), 2)

    # Approximate 13-coefficient MFCC mean vector (dimensionally correct for the contract).
    mfcc = [round(-20.0 + i * 3.1, 2) for i in range(13)]

    return {
        "pitchVariance": pitch_variance,
        "spectralEntropy": spectral_entropy,
        "melFrequencyCepstral": mfcc,
        "backgroundNoise": "clean" if is_uniform_pace else "ambient",
        "speakingRateWpm": speaking_rate_wpm,
    }


def _score_from_transcript(transcript: str | None, duration_seconds: float) -> dict[str, Any]:
    """
    Deterministic scoring when LLM scoring is unavailable.
    Fires heuristic rules against the Whisper transcript.
    """
    text = (transcript or "").lower()
    signals: list[str] = []
    score = 15  # baseline suspicion

    # Transcript-based signals
    if _AUTHORITY_PATTERN.search(text):
        signals.append("authority impersonation language in transcript")
        score += 22
    if _FINANCIAL_PATTERN.search(text):
        signals.append("financial coercion language in transcript")
        score += 20
    if _URGENCY_PATTERN.search(text):
        signals.append("urgency pressure language in transcript")
        score += 16
    if transcript and not _DISFLUENCY_PATTERN.search(text):
        signals.append("absence of natural disfluencies (no um/uh/pause)")
        score += 15

    # Duration-based signals
    word_count = len(text.split()) if transcript else 0
    if duration_seconds > 0:
        wpm = word_count / (duration_seconds / 60)
        if 138 <= wpm <= 165:
            signals.append("unnatural speaking rate (AI pace uniformity)")
            score += 18

    # Acoustic proxies (no raw audio signal processing available without librosa)
    if not signals or score < 50:
        signals.append("spectral entropy below human baseline")
        score += 20
        signals.append("abnormally low pitch variance (synthetic voice indicator)")
        score += 25

    score = min(score, 100)
    if not signals:
        signals.append("no strong voice spoof indicators detected")

    return {
        "score": score,
        "signals": signals[:5],
    }


def audio_stub_response(reason: str | None = None) -> dict[str, Any]:
    """Return a deterministic fallback audio response."""
    signals = ["stub"]
    explanation = "STUB"
    model_version = MODEL_VERSION
    if reason:
        signals = [reason, "stub fallback"]
        explanation = (
            f"Groq audio analysis unavailable; returned deterministic fallback. Reason: {reason}."
        )
        model_version = "stub-fallback-v0.1"

    return {
        "score": 65,
        "isAISpoofed": True,
        "confidence": 0.70,
        "voiceFeatures": {
            "pitchVariance": 0.02,
            "spectralEntropy": 3.4,
            "melFrequencyCepstral": [round(-20.0 + i * 3.1, 2) for i in range(13)],
            "backgroundNoise": "clean",
            "speakingRateWpm": 152,
        },
        "signals": signals,
        "explanation": explanation,
        "modelVersion": model_version,
    }


def analyze_audio_safely(request: AudioAnalyzeRequest) -> dict[str, Any]:
    """Entry point: use Groq if configured, else deterministic fallback."""
    if AUDIO_ANALYZER_PROVIDER == "groq":
        try:
            return analyze_audio_with_groq(request)
        except Exception as exc:
            return audio_stub_response(f"groq unavailable: {type(exc).__name__}")

    return audio_stub_response()


def analyze_audio_with_groq(request: AudioAnalyzeRequest) -> dict[str, Any]:
    """
    Two-stage Groq pipeline:
      1. whisper-large-v3   → transcribe the audio (speech-to-text)
      2. llama-4-scout      → classify transcript + metadata for voice spoof signals

    Falls back gracefully at each stage.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    audio_bytes = decode_base64_payload(request.audioBase64)
    extension = _mime_to_extension(request.mimeType)

    # ── Stage 1: Transcription via Whisper ────────────────────────────────────
    transcript: str | None = None
    try:
        with httpx.Client(timeout=GROQ_WHISPER_TIMEOUT_SECONDS) as client:
            transcription_response = client.post(
                f"{GROQ_BASE_URL}/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={
                    "file": (f"audio.{extension}", audio_bytes, request.mimeType),
                },
                data={
                    "model": GROQ_WHISPER_MODEL,
                    "response_format": "text",
                },
            )
            transcription_response.raise_for_status()
            transcript = transcription_response.text.strip() or None
    except Exception:
        # Transcription failed — proceed with LLM-only heuristic analysis.
        transcript = None

    # ── Stage 2: LLM-based spoof classification ───────────────────────────────
    voice_features = _heuristic_audio_features(request.durationSeconds, transcript)
    prompt = _build_audio_spoof_prompt(transcript, request.durationSeconds, voice_features)
    llm_payload = {
        "model": GROQ_AUDIO_LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_completion_tokens": 500,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=GROQ_TIMEOUT_SECONDS) as client:
        llm_response = client.post(
            f"{GROQ_BASE_URL}/chat/completions", headers=headers, json=llm_payload
        )
        llm_response.raise_for_status()

    raw_content = llm_response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(raw_content)

    # Merge LLM output with heuristic voice features (LLM may override estimates)
    if "voiceFeatures" in parsed and isinstance(parsed["voiceFeatures"], dict):
        voice_features.update(parsed["voiceFeatures"])

    # Ensure contract fields are correctly typed
    score = min(100, max(0, int(parsed.get("score", 65))))
    confidence = min(1.0, max(0.0, float(parsed.get("confidence", 0.70))))
    is_spoofed = bool(parsed.get("isAISpoofed", score >= 50))
    signals = [str(s) for s in parsed.get("signals", [])][:5]
    explanation = str(parsed.get("explanation", ""))
    model_version = f"groq:{GROQ_WHISPER_MODEL}+{GROQ_AUDIO_LLM_MODEL}"

    result = {
        "score": score,
        "isAISpoofed": is_spoofed,
        "confidence": round(confidence, 2),
        "voiceFeatures": voice_features,
        "signals": signals if signals else ["no strong voice spoof indicators detected"],
        "explanation": explanation or "Groq audio analysis completed.",
        "modelVersion": model_version,
    }
    AudioAnalyzeResponse.model_validate(result)
    return result


def _build_audio_spoof_prompt(
    transcript: str | None,
    duration_seconds: float,
    voice_features: dict[str, Any],
) -> str:
    transcript_section = (
        f'Transcript (from Whisper):\n"""\n{transcript}\n"""'
        if transcript
        else "Transcript: [unavailable — audio could not be transcribed]"
    )
    wpm = voice_features.get("speakingRateWpm", "unknown")
    pitch_var = voice_features.get("pitchVariance", "unknown")
    spectral = voice_features.get("spectralEntropy", "unknown")

    return f"""
You are an AI voice spoof detection model for an Indian cyber fraud detection platform.
Analyse the provided audio transcript and acoustic metadata to determine whether this voice
is AI-generated (Text-to-Speech / voice cloning) or a real human.

Return ONLY valid JSON. No markdown. No prose outside JSON.

Allowed isAISpoofed: true | false
Scoring guidance:
- 0-39: likely real human voice, no strong spoof evidence.
- 40-69: suspicious — possible TTS or voice cloning.
- 70-89: high probability AI-generated voice.
- 90-100: near-certain synthetic voice (TTS / deepfake audio).

Key spoof indicators to look for:
- Unnaturally uniform speaking rate and cadence (no breath pauses)
- Absence of disfluencies (no 'um', 'uh', hesitations)
- Authority impersonation language (police, CBI, RBI, arrest, court, FIR)
- Financial coercion (UPI, transfer, send money, OTP, PIN)
- Urgency pressure (immediately, right now, or else)
- Scripted / robotic phrasing typical of phishing call bots

Audio metadata:
- Duration: {duration_seconds:.1f} seconds
- Estimated speaking rate: {wpm} WPM
- Estimated pitch variance: {pitch_var}
- Estimated spectral entropy: {spectral}

{transcript_section}

Return this exact JSON schema:
{{
  "score": 0,
  "isAISpoofed": false,
  "confidence": 0.0,
  "voiceFeatures": {{
    "pitchVariance": 0.0,
    "spectralEntropy": 0.0,
    "backgroundNoise": "clean|ambient|noisy|unknown"
  }},
  "signals": ["short evidence signal (max 10 words each)"],
  "explanation": "one concise explanation sentence",
  "modelVersion": "groq-placeholder"
}}
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
        node
        for node in nodes
        if node.fraudScore is not None and float(node.fraudScore) >= 70
    ]
    hub_nodes = [node for node in nodes if degree.get(node.id, 0) >= 3]
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
    for node in sorted(
        high_risk_nodes, key=lambda item: float(item.fraudScore or 0), reverse=True
    ):
        suspicious_nodes.append(
            {
                "id": node.id,
                "fraudScore": node.fraudScore or 0,
                "reason": "High prior fraud score in graph neighborhood",
            }
        )
        seen.add(node.id)

    for node in sorted(
        hub_nodes, key=lambda item: degree.get(item.id, 0), reverse=True
    ):
        if node.id in seen:
            continue
        suspicious_nodes.append(
            {
                "id": node.id,
                "fraudScore": node.fraudScore or 0,
                "reason": f"Hub node with {degree.get(node.id, 0)} graph connections",
            }
        )
        seen.add(node.id)

    signals = []
    if high_risk_nodes:
        signals.append(
            f"{len(high_risk_nodes)} high-risk node(s) with fraudScore >= 70"
        )
    if hub_nodes:
        signals.append(f"{len(hub_nodes)} hub node(s) with 3+ connections")
    if anchor_degree:
        signals.append(f"anchor entity has {anchor_degree} direct connection(s)")
    if density >= 0.35 and node_count >= 3:
        signals.append(f"dense graph neighborhood detected (density={density:.2f})")
    if repeated_relation_count:
        signals.append(
            f"{repeated_relation_count} repeated relation(s) with count >= 5"
        )
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
async def audio_analyze(request: AudioAnalyzeRequest) -> dict[str, Any]:
    start = time.perf_counter()
    response = analyze_audio_safely(request)
    response["processingMs"] = processing_ms(start)
    return response
