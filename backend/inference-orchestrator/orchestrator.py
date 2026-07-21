"""
Inference Orchestrator — Core Engine

Implements the "Anchor and Expand" strategy (inference-orchestrator.md §Data Flow):
  1. Load FusionConfig from Redis (hot-reload, fresh per call)
  2. Determine active models (enabled ∩ onlyModels ∩ evidence-based activation)
  3. [Mode A only] Graph enrichment: GET /graph/linkages?entityId={anchor}&depth=2
  4. asyncio.gather() all active model calls with per-model timeout
  5. Re-normalize weights across responding models
  6. Compute fusedScore = weighted average of (score × confidence-adjusted weight)
  7. Classify: COMPLETE | INCOMPLETE | PENDING_REVIEW | FAILED
  8. Persist atomically (DB transaction)
  9. Publish Prediction.Completed or Prediction.Failed
 10. Return FusedVerdict dict

riskTier thresholds (inference-orchestrator.md line 67-73, postgres.sql line 253):
  LOW: 0-39 | MEDIUM: 40-69 | HIGH: 70-89 | CRITICAL: 90-100
  DB CHECK constraint: risk_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')

Status logic:
  All models None after retry → FAILED (no fused_verdicts row)
  Any model timed out / UNAVAILABLE → INCOMPLETE
  confidence < threshold (0.60) → PENDING_REVIEW
  All models responded + confidence >= threshold → COMPLETE

Retry policy (mode-aware — see ml_clients.py):
  Mode A: retry once at 500ms on 5xx/RequestError (T13 spec)
  Mode B: no retry — 500ms sleep violates 200ms interdiction budget
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import httpx

from database import db
from ml_clients import (
    call_audio_analyzer,
    call_counterfeit,
    call_graph_analyzer,
    call_scam_nlp,
    fetch_evidence_content,
    fetch_graph_linkages,
)
from publisher import publisher
from redis_client import FusionConfig, redis_client

logger = logging.getLogger("orch-engine")


# ── Request / Response Models ──────────────────────────────────────────────────

@dataclass
class ComplaintPayload:
    title: str
    description: str
    complaint_type: str
    suspect_phone: Optional[str] = None
    suspect_account: Optional[str] = None
    language_code: str = "en"


@dataclass
class EvidenceRef:
    evidence_id: str
    mime_type: str


@dataclass
class AnalyzeRequest:
    case_id: uuid.UUID
    trigger_type: str
    complaint: ComplaintPayload
    evidence_refs: List[EvidenceRef]
    sync: bool = False
    only_models: Optional[List[str]] = None
    correlation_id: Optional[uuid.UUID] = None


@dataclass
class FusedVerdict:
    prediction_id: uuid.UUID
    case_id: uuid.UUID
    fused_score: float
    risk_tier: str
    confidence: float
    status: str
    model_breakdown: List[Dict[str, Any]]
    explanation: str
    fusion_weights: Dict[str, float]
    pending_review: bool
    fusion_timestamp: str
    correlation_id: Optional[uuid.UUID]


# ── Tier classification ────────────────────────────────────────────────────────

def score_to_tier(score: float) -> str:
    """
    4-tier scheme from inference-orchestrator.md §riskTier thresholds.
    DB CHECK constraint on inference.fused_verdicts enforces this set.
    """
    if score >= 90:
        return "CRITICAL"
    elif score >= 70:
        return "HIGH"
    elif score >= 40:
        return "MEDIUM"
    return "LOW"


# ── Active model selection ────────────────────────────────────────────────────

def select_active_models(
    config: FusionConfig,
    complaint_type: str,
    evidence_refs: List[EvidenceRef],
    only_models: Optional[List[str]],
) -> Set[str]:
    """
    active = enabled_models
            ∩ only_models (if set — sync path)
            filtered by evidence-based activation rules
    """
    active = set(config.enabled_models)

    # only_models filter (sync interdiction path passes specific subset)
    if only_models:
        active = active.intersection(set(only_models))

    # Evidence-based activation:
    # counterfeit-cv: only for COUNTERFEIT_CURRENCY with image evidence
    has_image = any(r.mime_type.startswith("image/") for r in evidence_refs)
    if complaint_type != "COUNTERFEIT_CURRENCY" or not has_image:
        active.discard("counterfeit-cv")

    # audio-analyzer: only if audio evidence present
    has_audio = any(r.mime_type.startswith("audio/") for r in evidence_refs)
    if not has_audio:
        active.discard("audio-analyzer")

    return active


# ── Weight re-normalization ───────────────────────────────────────────────────

def renormalize_weights(
    weights: Dict[str, float],
    responding_models: Set[str],
) -> Dict[str, float]:
    """
    Redistribute weights across only the models that responded.
    Ensures fusedScore is always on the 0-100 scale even with partial failures.
    """
    active_w = {m: w for m, w in weights.items() if m in responding_models}
    total = sum(active_w.values())
    if total == 0:
        return {}
    return {m: w / total for m, w in active_w.items()}


# ── Core engine ───────────────────────────────────────────────────────────────

async def analyze(request: AnalyzeRequest, http_client: httpx.AsyncClient) -> FusedVerdict:
    """
    Main fusion engine. Called by:
      - kafka_consumer.py (Mode A, sync=False, onlyModels=None)
      - main.py POST /inference/analyze (Mode B if sync=True)
    """
    case_id_str = str(request.case_id)
    corr_id_str = str(request.correlation_id) if request.correlation_id else str(uuid.uuid4())

    logger.info(
        f"analyze() start case_id={case_id_str} trigger={request.trigger_type} "
        f"sync={request.sync} onlyModels={request.only_models}"
    )

    # Step 1: Load fusion config from Redis (hot-reload)
    config: FusionConfig = await redis_client.load_fusion_config()

    # Step 2: Determine active models
    active_models = select_active_models(
        config,
        request.complaint.complaint_type,
        request.evidence_refs,
        request.only_models,
    )
    logger.info(f"Active models for case {case_id_str}: {active_models}")

    if not active_models:
        logger.warning(f"No active models for case {case_id_str} — recording FAILED")
        pred_id = await db.persist_failed(
            request.case_id, request.trigger_type, request.correlation_id
        )
        publisher.publish_failed(
            pred_id, request.case_id, "No models enabled/applicable", request.correlation_id
        )
        return _make_failed_verdict(pred_id, request)

    # Step 3: [Mode A only] Graph enrichment (skipped in sync mode — 200ms budget)
    graph_data: Optional[dict] = None
    anchor = request.complaint.suspect_phone or request.complaint.suspect_account
    if not request.sync and anchor and "graph-analyzer" in active_models:
        graph_data = await fetch_graph_linkages(http_client, anchor)

    # Evidence IDs are references, not model payloads. Resolve verified bytes
    # before the parallel model fan-out.
    image_content: Optional[tuple[str, str]] = None
    audio_content: Optional[tuple[str, str]] = None
    if "counterfeit-cv" in active_models:
        image_ref = EvidenceRef(evidence_id=image_content[0] if image_content else "", mime_type="image/png")
        image_content = await fetch_evidence_content(http_client, image_ref.evidence_id, "image/")
    if "audio-analyzer" in active_models:
        audio_ref = EvidenceRef(
            evidence_id=audio_content[0] if audio_content else "",
            mime_type=audio_content[1] if audio_content else "audio/wav",
        )
        audio_content = await fetch_evidence_content(http_client, audio_ref.evidence_id, "audio/")

    # Step 4: Build coroutines for all active models
    tasks: Dict[str, asyncio.Task] = {}
    timeout = config.per_model_timeout_s

    async def run_with_timeout(coro):
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            return None

    if "scam-nlp" in active_models:
        tasks["scam-nlp"] = asyncio.create_task(run_with_timeout(
            call_scam_nlp(
                http_client,
                request.complaint.description,
                request.complaint.language_code,
                request.complaint.complaint_type,
                case_id_str, corr_id_str,
                sync_mode=request.sync,
            )
        ))

    if "graph-analyzer" in active_models:
        tasks["graph-analyzer"] = asyncio.create_task(run_with_timeout(
            call_graph_analyzer(
                http_client, anchor or "", graph_data,
                case_id_str, corr_id_str,
                sync_mode=request.sync,
            )
        ))

    # counterfeit: evidence_refs were already validated in select_active_models
    if "counterfeit-cv" in active_models:
        image_ref = next(r for r in request.evidence_refs if r.mime_type.startswith("image/"))
        tasks["counterfeit-cv"] = asyncio.create_task(run_with_timeout(
            call_counterfeit(
                http_client,
                image_ref.evidence_id,  # placeholder — real impl fetches from MinIO
                500,                    # denomination default
                case_id_str, corr_id_str,
                sync_mode=request.sync,
            )
        ))

    if "audio-analyzer" in active_models:
        audio_ref = next(r for r in request.evidence_refs if r.mime_type.startswith("audio/"))
        tasks["audio-analyzer"] = asyncio.create_task(run_with_timeout(
            call_audio_analyzer(
                http_client,
                audio_ref.evidence_id,  # placeholder — real impl fetches from MinIO
                audio_ref.mime_type,
                0.0,
                case_id_str, corr_id_str,
                sync_mode=request.sync,
            )
        ))

    # Step 5: Fan-out (parallel)
    raw_results: Dict[str, Optional[dict]] = {}
    if tasks:
        results = await asyncio.gather(*tasks.values(), return_exceptions=False)
        raw_results = dict(zip(tasks.keys(), results))

    responding = {m for m, r in raw_results.items() if r is not None}
    unavailable = set(raw_results.keys()) - responding

    logger.info(f"ML results: responding={responding} unavailable={unavailable}")

    # Step 6: Handle total failure (all models None)
    if not responding:
        logger.error(f"All models UNAVAILABLE for case {case_id_str}")
        pred_id = await db.persist_failed(
            request.case_id, request.trigger_type, request.correlation_id
        )
        publisher.publish_failed(
            pred_id, request.case_id, "All ML models unavailable", request.correlation_id
        )
        return _make_failed_verdict(pred_id, request)

    # Step 7: Re-normalize weights + compute fused score
    norm_weights = renormalize_weights(config.weights, responding)

    fused_score = sum(
        raw_results[m]["score"] * norm_weights.get(m, 0)
        for m in responding
        if "score" in raw_results[m]
    )
    # Confidence = weighted average of per-model confidence
    confidence = sum(
        raw_results[m].get("confidence", 0.5) * norm_weights.get(m, 0)
        for m in responding
    )

    risk_tier = score_to_tier(fused_score)

    # Step 8: Classify verdict status
    if unavailable:
        verdict_status = "INCOMPLETE"
        pending_review = True
    elif confidence < config.confidence_threshold:
        verdict_status = "PENDING_REVIEW"
        pending_review = True
    else:
        verdict_status = "COMPLETE"
        pending_review = False

    # Build model_breakdown (T13 / ml-contract.md §FusedVerdict)
    model_breakdown = []
    for model_name, result in raw_results.items():
        if result is None:
            model_breakdown.append({"model": model_name, "status": "UNAVAILABLE"})
        else:
            model_breakdown.append({
                "model": model_name,
                "score": result.get("score"),
                "confidence": result.get("confidence"),
                "riskTier": result.get("riskTier"),
                "signals": result.get("signals", []),
                "explanation": result.get("explanation", ""),
                "modelVersion": result.get("modelVersion", "unknown"),
                "latencyMs": result.get("processingMs"),
            })

    explanation = _build_explanation(model_breakdown, verdict_status, confidence)

    # Step 9: Persist (atomic transaction)
    prediction_db_status = "COMPLETE" if verdict_status != "FAILED" else "FAILED"
    prediction_id = await db.persist_verdict(
        case_id=request.case_id,
        trigger_type=request.trigger_type,
        correlation_id=request.correlation_id,
        fused_score=fused_score,
        risk_tier=risk_tier,
        confidence=confidence,
        verdict_status=verdict_status,
        prediction_status=prediction_db_status,
        model_breakdown=model_breakdown,
        explanation=explanation,
        fusion_weights=norm_weights,
        pending_review=pending_review,
    )

    # Step 10: Publish
    publisher.publish_completed(
        prediction_id=prediction_id,
        case_id=request.case_id,
        fused_score=fused_score,
        risk_tier=risk_tier,
        confidence=confidence,
        verdict_status=verdict_status,
        model_breakdown=model_breakdown,
        explanation=explanation,
        fusion_weights=norm_weights,
        pending_review=pending_review,
        correlation_id=request.correlation_id,
    )

    return FusedVerdict(
        prediction_id=prediction_id,
        case_id=request.case_id,
        fused_score=round(fused_score, 2),
        risk_tier=risk_tier,
        confidence=round(confidence, 3),
        status=verdict_status,
        model_breakdown=model_breakdown,
        explanation=explanation,
        fusion_weights=norm_weights,
        pending_review=pending_review,
        fusion_timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        correlation_id=request.correlation_id,
    )


def _build_explanation(breakdown: list, status: str, confidence: float) -> str:
    responding = [b for b in breakdown if b.get("status") != "UNAVAILABLE"]
    unavailable = [b["model"] for b in breakdown if b.get("status") == "UNAVAILABLE"]
    parts = [f"{b['model']}: {b.get('explanation', '')}" for b in responding if b.get("explanation")]
    base = "Multi-model consensus: " + " | ".join(parts) if parts else "Partial ML analysis."
    if unavailable:
        base += f" Models unavailable: {', '.join(unavailable)}."
    if status == "PENDING_REVIEW":
        base += f" Confidence {confidence:.0%} below threshold — routed for human review."
    return base


def _make_failed_verdict(pred_id: uuid.UUID, request: AnalyzeRequest) -> FusedVerdict:
    return FusedVerdict(
        prediction_id=pred_id,
        case_id=request.case_id,
        fused_score=0.0,
        risk_tier="LOW",
        confidence=0.0,
        status="INCOMPLETE",
        model_breakdown=[],
        explanation="All ML models unavailable. Case requires manual investigation.",
        fusion_weights={},
        pending_review=True,
        fusion_timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        correlation_id=request.correlation_id,
    )
