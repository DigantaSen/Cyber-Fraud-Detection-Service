"""
Case Service — core business logic for Case Management.

CRITICAL PATTERN:
  Every multi-step write (case + outbox + timeline) is wrapped in a single
  `async with self._db.begin()` block. If any step fails the entire
  transaction rolls back — the outbox entry and the domain row are NEVER
  written independently.

ML stub:
  _ML_STUB_VERDICT is a module-level constant returned by _to_detail_response()
  until T13 (Day 6) wires up the real Inference Orchestrator HTTP call.
  Replace the constant and the _to_detail_response method body at T13.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    CaseDetailResponse,
    CreateCaseRequest,
    CreateCaseResponse,
    PredictionSummary,
    UpdateCaseStateRequest,
    VerdictOverrideRequest,
)
from repositories.case_repository import CaseRepository
from repositories.idempotency_repository import IdempotencyRepository
from repositories.outbox_repository import OutboxRepository
from repositories.override_repository import OverrideRepository
from repositories.prediction_repository import PredictionRepository
from repositories.timeline_repository import TimelineRepository
from state_machine.transitions import (
    TransitionError,
    TransitionPermissionError,
    validate_transition,
)


# ── ML stub (replaced in T13 Day 6) ──────────────────────────────────────────
# Assumptions: see surjit/notes/assumptions.md → T5a — Case Service: ML Stub
_ML_STUB_VERDICT = {
    "fusedScore": 72.0,
    "riskTier": "HIGH",
    "confidence": 0.85,
    "status": "COMPLETE",
    "modelBreakdown": [
        {"model": "scam-nlp", "score": 78, "confidence": 0.88},
    ],
    "explanation": "Stub verdict — AI integration pending (T13).",
}


# ── Domain exceptions (router maps to HTTP status codes) ─────────────────────

class CaseNotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


class CasePermissionError(Exception):
    pass


class DuplicateCaseError(Exception):
    pass


# ── Service ───────────────────────────────────────────────────────────────────

class CaseService:

    def __init__(self, db: AsyncSession):
        self._db = db
        self._case_repo = CaseRepository(db)
        self._timeline_repo = TimelineRepository(db)
        self._override_repo = OverrideRepository(db)
        self._outbox_repo = OutboxRepository(db)
        self._idempotency_repo = IdempotencyRepository(db)

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_case(
        self,
        req: CreateCaseRequest,
        reporter_user_id: uuid.UUID,
        jurisdiction_id: str,
        correlation_id: uuid.UUID,
        idempotency_key: uuid.UUID,
    ) -> CreateCaseResponse:
        """
        Create a new case and write Case.Created to the outbox.
        Both writes are in a SINGLE transaction — atomic unit of work.

        Idempotency:
          If the same Idempotency-Key was already processed the cached
          CreateCaseResponse is returned immediately without touching the DB.
        """
        # 1. Idempotency check — return cached result if key already processed.
        existing = await self._idempotency_repo.get(idempotency_key)
        if existing:
            return CreateCaseResponse(**existing.response_body["data"])

        # 2. Generate case number OUTSIDE the transaction (read-only COUNT).
        case_number = await self._case_repo.generate_case_number()

        # 3. Atomic write: case + outbox + timeline in one transaction.
        case = await self._case_repo.create(
            case_data={
                "title": req.title,
                "description": req.description,
                "complaint_type": req.complaint_type,
                "suspect_phone": req.suspect_phone,
                "suspect_account": req.suspect_account,
                "complaint_lat": req.complaint_lat,
                "complaint_lon": req.complaint_lon,
                "reporter_user_id": reporter_user_id,
                "reporter_entity_name": req.reporter_entity_name,
                "reporter_phone": req.reporter_phone,
                "language_code": req.language_code,
                "jurisdiction_id": jurisdiction_id,
                "status": "New",
            },
            case_number=case_number,
        )

        now = datetime.now(timezone.utc).isoformat()

        # Publish Case.Created → outbox (same transaction).
        await self._outbox_repo.publish(
            aggregate_type="Case",
            aggregate_id=case.case_id,
            event_type="Case.Created",
            topic="case.created",
            event_key=str(case.case_id),
            payload={
                "caseId": str(case.case_id),
                "caseNumber": case_number,
                "title": req.title,
                "description": req.description,
                "complaintType": req.complaint_type,
                "suspectPhone": req.suspect_phone,
                "suspectAccount": req.suspect_account,
                "complaintLat": req.complaint_lat,
                "complaintLon": req.complaint_lon,
                "jurisdictionId": jurisdiction_id,
                "languageCode": req.language_code,
                "reporterUserId": str(reporter_user_id),
                "createdAt": now,
            },
            correlation_id=correlation_id,
        )

        # Append first timeline event (same transaction).
        await self._timeline_repo.append(
            case_id=case.case_id,
            event_type="Case.Created",
            description="Case created via Citizen BFF",
            actor_id=reporter_user_id,
            actor_role="CITIZEN",
            correlation_id=correlation_id,
        )

        # Store idempotency record so replay returns the same response.
        response_data = {
            "case_id": str(case.case_id),
            "case_number": case_number,
            "status": "New",
            "created_at": case.created_at.isoformat(),
            "assigned_to": None,
            "prediction_status": "PENDING",
        }
        await self._idempotency_repo.store(
            idempotency_key=idempotency_key,
            request_hash=_hash_request(req.model_dump()),
            response_status=201,
            response_body={"data": response_data},
        )
        await self._db.commit()

        return CreateCaseResponse(
            case_id=case.case_id,
            case_number=case_number,
            status="New",
            created_at=case.created_at,
            assigned_to=None,
            prediction_status="PENDING",
        )

    # ── Get ───────────────────────────────────────────────────────────────────

    async def get_case(
        self,
        case_id: uuid.UUID,
        jurisdiction_id: str,
    ) -> CaseDetailResponse:
        """
        Fetch a single case by ID.
        RBAC: jurisdiction_id from JWT must match case.jurisdiction_id.
        Prediction is the ML stub until T13.
        """
        case = await self._case_repo.get_by_id(case_id)
        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        if case.jurisdiction_id != jurisdiction_id:
            raise CasePermissionError("Case does not belong to your jurisdiction")

        return await self._to_detail_response(case)

    # ── State Transition ──────────────────────────────────────────────────────

    async def update_state(
        self,
        case_id: uuid.UUID,
        req: UpdateCaseStateRequest,
        caller_role: str,
        caller_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> CaseDetailResponse:
        """
        Validate the requested state transition, then atomically:
          1. Update case.status in DB
          2. Write Case.Updated to outbox
          3. Append timeline event
        Raises InvalidTransitionError BEFORE any DB write on invalid transitions.
        """
        case = await self._case_repo.get_by_id(case_id)
        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        # Validate BEFORE touching DB — pure function, no I/O.
        try:
            validate_transition(
                current_state=case.status,
                new_state=req.state,
                reason=req.reason,
                caller_role=caller_role,
            )
        except TransitionError as e:
            raise InvalidTransitionError(str(e)) from e
        except TransitionPermissionError as e:
            raise CasePermissionError(str(e)) from e

        event_type = "Case.Assigned" if req.assigned_to else "Case.Updated"
        topic = "case.assigned" if req.assigned_to else "case.updated"

        updated = await self._case_repo.update_state(
            case_id=case_id,
            new_state=req.state,
            assigned_investigator=req.assigned_to,
        )

        await self._outbox_repo.publish(
            aggregate_type="Case",
            aggregate_id=case_id,
            event_type=event_type,
            topic=topic,
            event_key=str(case_id),
            payload={
                "caseId": str(case_id),
                "previousState": case.status,
                "newState": req.state,
                "reason": req.reason,
                "assignedTo": str(req.assigned_to) if req.assigned_to else None,
            },
            correlation_id=correlation_id,
        )

        await self._timeline_repo.append(
            case_id=case_id,
            event_type=event_type,
            description=f"State changed: {case.status} → {req.state}. Reason: {req.reason}",
            actor_id=caller_id,
            actor_role=caller_role,
            correlation_id=correlation_id,
        )
        await self._db.commit()

        return await self._to_detail_response(updated)

    # ── Pending Review (Inference Callback) ───────────────────────────────────

    async def set_pending_review(
        self,
        case_id: uuid.UUID,
        prediction_payload: dict,
        correlation_id: uuid.UUID,
    ) -> None:
        """
        Called by Inference Orchestrator (T13) when confidence < 0.60.
        1. Insert FusedVerdict with pending_review=True, pending_notification=True
        2. Transition case to Pending_AI
        3. Write Case.Updated + Prediction.PendingReview outbox events
        4. Append timeline entry
        All in ONE transaction.
        """
        case = await self._case_repo.get_by_id(case_id)
        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        if case.status not in ("Investigating", "Assigned"):
            raise InvalidTransitionError(
                f"Case must be Investigating to receive HITL callback, got {case.status}"
            )

        pred_repo = PredictionRepository(self._db)

        # 1. Persist FusedVerdict (append-only)
        verdict = await pred_repo.insert(
            case_id=case_id,
            fused_score=prediction_payload.get("fusedScore", 0.0),
            risk_tier=prediction_payload.get("riskTier", "MEDIUM"),
            confidence=prediction_payload.get("confidence", 0.0),
            status="PENDING_REVIEW",
            model_breakdown=prediction_payload.get("modelBreakdown", []),
            explanation=prediction_payload.get("explanation", "Below confidence threshold — HITL required."),
            fusion_weights=prediction_payload.get("fusionWeights"),
            pending_review=True,
            pending_notification=True,   # Suppress citizen notification until APPROVE
            correlation_id=correlation_id,
        )

        # 2. Transition case to Pending_AI
        await self._case_repo.update_state(
            case_id=case_id,
            new_state="Pending_AI",
        )

        # 3. Outbox events
        await self._outbox_repo.publish(
            aggregate_type="Case",
            aggregate_id=case_id,
            event_type="Case.Updated",
            topic="case.updated", event_key=str(case_id),
            payload={
                "caseId": str(case_id),
                "newState": "Pending_AI",
                "reason": "PENDING_REVIEW",
                "predictionId": str(verdict.prediction_id),
            },
            correlation_id=correlation_id,
        )
        await self._outbox_repo.publish(
            aggregate_type="Prediction",
            aggregate_id=case_id,
            event_type="Prediction.PendingReview",
            topic="prediction.overridden", event_key=str(case_id),
            payload={
                "caseId": str(case_id),
                "predictionId": str(verdict.prediction_id),
                "fusedScore": prediction_payload.get("fusedScore"),
                "riskTier": prediction_payload.get("riskTier"),
                "confidence": prediction_payload.get("confidence"),
            },
            correlation_id=correlation_id,
        )

        # 4. Timeline
        await self._timeline_repo.append(
            case_id=case_id,
            event_type="Prediction.PendingReview",
            description=(
                f"AI confidence {prediction_payload.get('confidence', 0)*100:.0f}% below threshold. "
                f"Routed to HITL review. Risk: {prediction_payload.get('riskTier')} "
                f"({prediction_payload.get('fusedScore', 0.0):.0f}/100)"
            ),
            correlation_id=correlation_id,
        )
        await self._db.commit()

    # ── Verdict Override ──────────────────────────────────────────────────────

    async def override_verdict(
        self,
        case_id: uuid.UUID,
        req: VerdictOverrideRequest,
        investigator_id: uuid.UUID,
        correlation_id: uuid.UUID,
    ) -> dict:
        """
        Human-in-the-loop verdict override (HITL).

        APPROVE → new_state = Action_Taken (resume automated actions)
        REJECT  → new_state = Closed, disposition = FALSE_POSITIVE

        Atomically writes: OverrideRecord + state update + outbox + timeline.
        """
        case = await self._case_repo.get_by_id(case_id)
        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        if case.status not in ("Pending_AI", "Action_Taken"):
            raise InvalidTransitionError(
                f"Verdict override requires Pending_AI or Action_Taken status, got '{case.status}'"
            )

        new_state = "Action_Taken" if req.decision == "APPROVE" else "Closed"
        disposition = "FALSE_POSITIVE" if req.decision == "REJECT" else None

        # APPEND-ONLY — DB trigger prevents future UPDATE/DELETE.
        override = await self._override_repo.create(
            case_id=case_id,
            original_verdict_id=req.original_verdict_id,
            decision=req.decision,
            justification=req.justification,
            investigator_id=investigator_id,
            original_score=None,        # populated if fused_verdict is fetched
            original_confidence=None,
            correlation_id=correlation_id,
        )

        await self._case_repo.update_state(
            case_id=case_id,
            new_state=new_state,
            disposition=disposition,
        )

        await self._outbox_repo.publish(
            aggregate_type="Case",
            aggregate_id=case_id,
            event_type="Prediction.Overridden",
            topic="prediction.overridden",
            event_key=str(case_id),
            payload={
                "caseId": str(case_id),
                "decision": req.decision,
                "overrideId": str(override.override_id),
                "investigatorId": str(investigator_id),
                "originalVerdictId": str(req.original_verdict_id),
                "newState": new_state,
                "disposition": disposition,
            },
            correlation_id=correlation_id,
        )

        await self._timeline_repo.append(
            case_id=case_id,
            event_type="Verdict.Overridden",
            description=(
                f"Investigator {req.decision.lower()}d AI verdict. "
                f"Justification: {req.justification[:100]}"
            ),
            actor_id=investigator_id,
            actor_role="INVESTIGATOR",
            correlation_id=correlation_id,
        )
        await self._db.commit()

        if req.decision == "APPROVE":
            # Resume suppressed notification (Prediction.Overridden triggers Notification via Kafka)
            # Direct HTTP call to Notification Service added in T13b (Day 7)
            # For now: publish Notification.Requested to outbox so Diganta's integration picks it up
            await self._outbox_repo.publish(
                aggregate_type="Notification",
                aggregate_id=case_id,
                event_type="Notification.Requested",
                topic="notification.requested", event_key=str(case_id),
                payload={"caseId": str(case_id), "trigger": "HITL_APPROVED"},
                correlation_id=correlation_id,
            )
            await self._db.commit()

        return {
            "overrideId": str(override.override_id),
            "decision": req.decision,
            "caseId": str(case_id),
            "investigatorId": str(investigator_id),
            "originalVerdictId": str(req.original_verdict_id),
            "timestamp": override.created_at.isoformat(),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    async def apply_prediction_result(
        self,
        prediction_payload: dict,
        correlation_id: uuid.UUID,
    ) -> None:
        """Apply a published inference result without duplicating its verdict row.

        The Orchestrator owns writes to ``inference.predictions`` and
        ``inference.fused_verdicts``.  Case Service only changes workflow state
        and appends an audit timeline entry for review-required outcomes.
        """
        case_id = uuid.UUID(prediction_payload["caseId"])
        case = await self._case_repo.get_by_id(case_id)
        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        review_required = (
            prediction_payload.get("pendingReview", False)
            or prediction_payload.get("status") in {"INCOMPLETE", "PENDING_REVIEW"}
        )
        if not review_required or case.status == "Pending_AI":
            return

        validate_transition(case.status, "Pending_AI", "PREDICTION_REQUIRES_REVIEW", "SYSTEM")
        await self._case_repo.update_state(case_id, "Pending_AI")
        await self._outbox_repo.publish(
            aggregate_type="Case",
            aggregate_id=case_id,
            event_type="Case.Updated",
            topic="case.updated",
            event_key=str(case_id),
            payload={
                "caseId": str(case_id),
                "newState": "Pending_AI",
                "reason": prediction_payload.get("status", "PREDICTION_REQUIRES_REVIEW"),
                "predictionId": prediction_payload.get("predictionId"),
            },
            correlation_id=correlation_id,
        )
        await self._timeline_repo.append(
            case_id=case_id,
            event_type="Prediction.PendingReview",
            description=(
                f"AI result {prediction_payload.get('status')} requires human review. "
                f"Confidence: {float(prediction_payload.get('confidence', 0)):.0%}."
            ),
            metadata={
                "predictionId": prediction_payload.get("predictionId"),
                "status": prediction_payload.get("status"),
            },
            correlation_id=correlation_id,
        )
        await self._db.commit()

    async def _to_detail_response(self, case) -> CaseDetailResponse:
        """
        Convert Case ORM → CaseDetailResponse.
        prediction: ML stub until T13 wires the real Inference Orchestrator.
        evidence_count: 0 stub until T14 cross-wiring (see assumptions.md).
        """
        verdict = await PredictionRepository(self._db).latest_for_case(case.case_id)
        prediction = None
        if verdict:
            prediction = PredictionSummary(
                prediction_id=verdict.prediction_id,
                fused_score=verdict.fused_score,
                risk_tier=verdict.risk_tier,
                confidence=verdict.confidence,
                status=verdict.status,
                model_breakdown=verdict.model_breakdown,
                explanation=verdict.explanation,
                created_at=verdict.fusion_timestamp,
            )
        return CaseDetailResponse(
            case_id=case.case_id,
            case_number=case.case_number,
            status=case.status,
            title=case.title,
            description=case.description,
            complaint_type=case.complaint_type,
            suspect_phone=case.suspect_phone,
            complaint_lat=case.complaint_lat,
            complaint_lon=case.complaint_lon,
            reporter_entity_name=case.reporter_entity_name,
            reporter_phone=case.reporter_phone,
            language_code=case.language_code,
            assigned_to=case.assigned_investigator,
            jurisdiction_id=case.jurisdiction_id,
            priority=case.priority,
            prediction=prediction,
            evidence_count=0,   # TODO T14: count from evidence.evidence table
            created_at=case.created_at,
            updated_at=case.updated_at,
        )


# ── Module-level helpers ───────────────────────────────────────────────────────

def _hash_request(data: dict) -> str:
    """Deterministic SHA-256 of request body dict for idempotency comparison."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()
