"""
Inference Orchestrator — ML Clients

Typed httpx wrappers for all 4 ML model endpoints (ml-contract.md).
All functions return None on any failure — the orchestrator treats None as UNAVAILABLE.

Retry policy (T13 spec, Execution.md line 779 + T17 test line 790):
  Mode A (sync_mode=False, Kafka-driven):
    On 5xx or httpx.RequestError → await 500ms → one retry.
    On second failure OR timeout → return None.
    T17 asserts exactly 2 httpx calls on a 504 response.

  Mode B (sync_mode=True, interdiction path, 200ms budget):
    Skip retry entirely — any failure → return None immediately.
    Rationale: 500ms sleep > the entire 200ms ML budget. Adding retry
    guarantees SLA breach on any transient error in the sync path.

Shared httpx.AsyncClient:
  Created once at app startup with connection pooling:
    httpx.Limits(max_connections=50, max_keepalive_connections=20)
  Passed in via dependency injection — never created per-request.
"""

import asyncio
import base64
import logging
from typing import Any, Dict, Optional

import httpx

from config import settings

logger = logging.getLogger("orch-ml")


# ── Retry helper ───────────────────────────────────────────────────────────────

async def _call_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    *,
    sync_mode: bool = False,
) -> Optional[dict]:
    """
    POST to an ML endpoint. Returns parsed JSON dict on success, None on failure.

    Mode A (sync_mode=False): retry once after 500ms on 5xx / RequestError.
    Mode B (sync_mode=True):  no retry — return None immediately on any failure.
    """
    for attempt in range(1, 3):  # max 2 attempts in Mode A, 1 in Mode B
        try:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return resp.json()
            # 5xx → retryable in Mode A
            if resp.status_code >= 500 and not sync_mode and attempt == 1:
                logger.warning(f"ML endpoint {url} returned {resp.status_code}, retrying in 500ms")
                await asyncio.sleep(0.5)
                continue
            logger.error(f"ML endpoint {url} returned HTTP {resp.status_code} — marking UNAVAILABLE")
            return None
        except httpx.TimeoutException:
            logger.warning(f"ML endpoint {url} timed out (attempt {attempt})")
            return None  # timeout: no retry regardless of mode
        except httpx.RequestError as e:
            if not sync_mode and attempt == 1:
                logger.warning(f"ML endpoint {url} network error: {e}, retrying in 500ms")
                await asyncio.sleep(0.5)
                continue
            logger.error(f"ML endpoint {url} network error after retry: {e} — marking UNAVAILABLE")
            return None
    return None


# ── Graph Enrichment (not an ML model — no retry, not mode-gated) ──────────────

async def fetch_graph_linkages(
    client: httpx.AsyncClient,
    anchor: str,
    depth: int = 2,
) -> Optional[dict]:
    """
    GET /graph/linkages?entityId={anchor}&depth={depth}
    Returns the 2-hop sub-graph JSON for the graph-analyzer ML payload.
    On failure → returns empty graph dict (orchestrator proceeds without graph).
    Not subject to retry: graph enrichment is only used in Mode A and is sequential.
    """
    try:
        url = f"{settings.GRAPH_SERVICE_URL}/graph/linkages"
        resp = await client.get(url, params={"entityId": anchor, "hops": depth})
        if resp.status_code == 200:
            return resp.json().get("data", {})
        logger.warning(f"Graph service returned {resp.status_code} for anchor={anchor} — proceeding without graph")
        return None
    except Exception as exc:
        logger.warning("Graph service unreachable for anchor=%s: %s", anchor, exc)
        return None


async def fetch_evidence_content(
    client: httpx.AsyncClient,
    evidence_id: str,
    expected_mime_prefix: str,
) -> Optional[tuple[str, str]]:
    """Return verified evidence as ``(base64, mimeType)`` for ML inference.

    Evidence is fetched through the Evidence Service's short-lived download URL;
    opaque evidence IDs must never be sent to a model as though they were bytes.
    """
    try:
        metadata = await client.get(
            f"{settings.EVIDENCE_SERVICE_URL}/evidence/{evidence_id}"
        )
        if metadata.status_code != 200:
            logger.warning("Evidence %s is unavailable for ML: HTTP %s", evidence_id, metadata.status_code)
            return None
        body = metadata.json()
        download_url = body.get("downloadUrl")
        if not download_url:
            return None

        content_response = await client.get(download_url)
        content_response.raise_for_status()
        mime_type = content_response.headers.get("content-type", "").split(";", 1)[0]
        if not mime_type.startswith(expected_mime_prefix):
            logger.warning("Evidence %s MIME %s does not match %s", evidence_id, mime_type, expected_mime_prefix)
            return None

        # Mirrors the ML contracts: images <= 5 MB, audio <= 50 MB.
        max_bytes = 5 * 1024 * 1024 if expected_mime_prefix == "image/" else 50 * 1024 * 1024
        if len(content_response.content) > max_bytes:
            logger.warning("Evidence %s exceeds the ML size limit", evidence_id)
            return None
        return base64.b64encode(content_response.content).decode("ascii"), mime_type
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not fetch evidence %s for ML: %s", evidence_id, exc)
        return None
    except Exception as e:
        logger.warning(f"Graph service unreachable for anchor={anchor}: {e} — proceeding without graph")
        return None


# ── Scam NLP ──────────────────────────────────────────────────────────────────

async def call_scam_nlp(
    client: httpx.AsyncClient,
    complaint_text: str,
    language_code: str,
    complaint_type: str,
    case_id: str,
    correlation_id: str,
    *,
    sync_mode: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    POST /ml/scam-classify (port 8100 internally)
    Returns: {score, riskTier, category, confidence, signals[], explanation, modelVersion, processingMs}
    """
    payload = {
        "text": complaint_text[:5000],  # max 5000 chars per ml-contract.md
        "languageCode": language_code,
        "complaintType": complaint_type,
        "metadata": {"correlationId": correlation_id, "caseId": case_id},
    }
    url = f"{settings.ML_SCAM_NLP_URL}/ml/scam-classify"
    result = await _call_with_retry(client, url, payload, sync_mode=sync_mode)
    if result:
        result["model"] = "scam-nlp"
    return result


# ── Graph Analyzer ────────────────────────────────────────────────────────────

async def call_graph_analyzer(
    client: httpx.AsyncClient,
    anchor_entity_id: str,
    graph_data: Optional[dict],
    case_id: str,
    correlation_id: str,
    *,
    sync_mode: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    POST /ml/graph-analyze (port 8102 internally)
    graph_data: output from fetch_graph_linkages (nodes + edges).
    Returns: {score, fraudRingProbability, suspiciousNodes[], ringSize, signals[], explanation, ...}
    """
    if graph_data is None:
        # No graph → empty stub graph (model still runs but with minimal context)
        graph_data = {"nodes": [], "edges": []}

    payload = {
        "anchorEntityId": anchor_entity_id,
        "graph": graph_data,
        "metadata": {"correlationId": correlation_id, "caseId": case_id},
    }
    url = f"{settings.ML_GRAPH_URL}/ml/graph-analyze"
    result = await _call_with_retry(client, url, payload, sync_mode=sync_mode)
    if result:
        result["model"] = "graph-analyzer"
    return result


# ── Counterfeit CV ────────────────────────────────────────────────────────────

async def call_counterfeit(
    client: httpx.AsyncClient,
    image_b64: str,
    denomination: int,
    case_id: str,
    correlation_id: str,
    *,
    sync_mode: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    POST /ml/counterfeit-detect (port 8101 internally)
    Only invoked when complaint_type=COUNTERFEIT_CURRENCY AND image evidence exists.
    Returns: {score, isAuthentic, confidence, detectedFeatures, signals[], explanation, ...}
    """
    payload = {
        "imageBase64": image_b64,
        "denomination": denomination,
        "metadata": {"correlationId": correlation_id, "caseId": case_id},
    }
    url = f"{settings.ML_COUNTERFEIT_URL}/ml/counterfeit-detect"
    result = await _call_with_retry(client, url, payload, sync_mode=sync_mode)
    if result:
        result["model"] = "counterfeit-cv"
    return result


# ── Audio Analyzer ────────────────────────────────────────────────────────────

async def call_audio_analyzer(
    client: httpx.AsyncClient,
    audio_b64: str,
    mime_type: str,
    duration_seconds: float,
    case_id: str,
    correlation_id: str,
    *,
    sync_mode: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    POST /ml/audio-analyze (port 8103 internally)
    Only invoked when audio/* evidence refs are present in the request.
    Returns: {score, isAISpoofed, confidence, voiceFeatures, signals[], explanation, ...}
    """
    payload = {
        "audioBase64": audio_b64,
        "mimeType": mime_type,
        "durationSeconds": duration_seconds,
        "metadata": {"correlationId": correlation_id, "caseId": case_id},
    }
    url = f"{settings.ML_AUDIO_URL}/ml/audio-analyze"
    result = await _call_with_retry(client, url, payload, sync_mode=sync_mode)
    if result:
        result["model"] = "audio-analyzer"
    return result
