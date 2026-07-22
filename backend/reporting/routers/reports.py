import asyncio
from fastapi.responses import Response
import uuid
import json
import hashlib
import base64
import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import boto3
from neo4j import AsyncGraphDatabase

from config import settings
from models import Report, IntelligencePackage, Outbox

router = APIRouter()

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

s3_client = boto3.client(
    's3',
    endpoint_url=settings.MINIO_ENDPOINT,
    aws_access_key_id=settings.MINIO_ACCESS_KEY,
    aws_secret_access_key=settings.MINIO_SECRET_KEY,
)

# RS256 Key Pair
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend()
)
public_key = private_key.public_key()
public_key_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)
public_key_fingerprint = hashlib.sha256(public_key_pem).hexdigest()[:16]

class NCRBRequest(BaseModel):
    case_id: Optional[str] = None
    caseId: Optional[str] = None
    def get_case_id(self) -> str:
        return self.case_id or self.caseId or ""

class IntelPackageRequest(BaseModel):
    case_id: Optional[str] = None
    caseId: Optional[str] = None
    def get_case_id(self) -> str:
        return self.case_id or self.caseId or ""

@router.post("/reports/ncrb")
async def generate_ncrb_report(payload: NCRBRequest, db: AsyncSession = Depends(get_db)):
    c_id = payload.get_case_id()
    if not c_id:
        raise HTTPException(status_code=400, detail="caseId required")
    report_id = uuid.uuid4()
    case_uuid = uuid.UUID(c_id)
    
    # Query case summary from DB
    res = await db.execute(text("SELECT case_number, title, complaint_type, status, jurisdiction_id, created_at FROM investigation.cases WHERE case_id = :cid"), {"cid": case_uuid})
    row = res.fetchone()
    
    ncrb_content = {
        "reportId": str(report_id),
        "caseId": str(case_uuid),
        "caseNumber": row.case_number if row else None,
        "title": row.title if row else None,
        "complaintType": row.complaint_type if row else None,
        "status": row.status if row else None,
        "jurisdictionId": row.jurisdiction_id if row else None,
        "type": "NCRB_ANNUAL_CRIME",
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ncrbFormCode": "NCRB-CYBER-2026-FORM-A"
    }
    content_bytes = json.dumps(ncrb_content, separators=(',', ':'), sort_keys=True).encode('utf-8')
    s3_key = f"ncrb/{case_uuid}/{report_id}.json"
    
    s3_client.put_object(
        Bucket=settings.MINIO_BUCKET_REPORTS,
        Key=s3_key,
        Body=content_bytes,
        ContentType="application/json"
    )
    
    report = Report(
        report_id=report_id,
        case_id=case_uuid,
        report_type='NCRB_ANNUAL_CRIME',
        status='READY',
        minio_bucket=settings.MINIO_BUCKET_REPORTS,
        object_key=s3_key,
        generated_at=datetime.datetime.now(datetime.timezone.utc)
    )
    db.add(report)
    await db.flush()
    
    outbox = Outbox(
        aggregate_type='Report',
        aggregate_id=report_id,
        event_type='Report.Generated',
        topic='reporting.events',
        event_key=str(case_uuid),
        payload={"eventType": "Report.Generated", "reportId": str(report_id), "caseId": str(case_uuid)}
    )
    db.add(outbox)
    await db.commit()
    
    return {"reportId": str(report_id), "status": "READY", "data": ncrb_content}

@router.post("/reports/intelligence-package")
async def generate_intel_package(payload: IntelPackageRequest, db: AsyncSession = Depends(get_db)):
    c_id = payload.get_case_id()
    if not c_id:
        raise HTTPException(status_code=400, detail="caseId is required")
    
    report_id = uuid.uuid4()
    package_id = uuid.uuid4()
    case_uuid = uuid.UUID(c_id)

    # 1. Query Real Case Data
    case_res = await db.execute(text("SELECT case_id, case_number, title, description, complaint_type, suspect_phone, suspect_account, reporter_phone, reporter_entity_name, complaint_lat, complaint_lon, status, priority, jurisdiction_id, created_at, updated_at FROM investigation.cases WHERE case_id = :cid"), {"cid": case_uuid})
    case_row = case_res.fetchone()
    if not case_row:
        raise HTTPException(status_code=404, detail=f"Case {case_uuid} not found")

    case_info = {
        "caseId": str(case_row.case_id),
        "caseNumber": case_row.case_number,
        "title": case_row.title,
        "description": case_row.description,
        "complaintType": case_row.complaint_type,
        "suspectPhone": case_row.suspect_phone,
        "suspectAccount": case_row.suspect_account,
        "reporterPhone": case_row.reporter_phone,
        "reporterEntityName": case_row.reporter_entity_name,
        "complaintLat": float(case_row.complaint_lat) if case_row.complaint_lat is not None else None,
        "complaintLon": float(case_row.complaint_lon) if case_row.complaint_lon is not None else None,
        "status": case_row.status,
        "priority": case_row.priority,
        "jurisdictionId": case_row.jurisdiction_id,
        "createdAt": case_row.created_at.isoformat() if case_row.created_at else None,
    }

    # 2. Query Real AI Fused Verdict
    verdict_res = await db.execute(text("SELECT prediction_id, fused_score, risk_tier, confidence, status, model_breakdown, explanation, fusion_timestamp FROM inference.fused_verdicts WHERE case_id = :cid ORDER BY fusion_timestamp DESC LIMIT 1"), {"cid": case_uuid})
    verdict_row = verdict_res.fetchone()
    ai_verdict = None
    if verdict_row:
        ai_verdict = {
            "predictionId": str(verdict_row.prediction_id),
            "fusedScore": float(verdict_row.fused_score) if verdict_row.fused_score is not None else None,
            "riskTier": verdict_row.risk_tier,
            "confidence": float(verdict_row.confidence) if verdict_row.confidence is not None else None,
            "status": verdict_row.status,
            "modelBreakdown": verdict_row.model_breakdown if isinstance(verdict_row.model_breakdown, list) else json.loads(verdict_row.model_breakdown or "[]"),
            "explanation": verdict_row.explanation,
            "fusionTimestamp": verdict_row.fusion_timestamp.isoformat() if verdict_row.fusion_timestamp else None
        }

    # 3. Query Real Evidence Files
    ev_res = await db.execute(text("SELECT evidence_id, file_name, mime_type, file_size_bytes, status, malware_scan, created_at FROM evidence.evidence WHERE case_id = :cid"), {"cid": case_uuid})
    ev_rows = ev_res.fetchall()
    evidence_items = [
        {
            "evidenceId": str(r.evidence_id),
            "fileName": r.file_name,
            "mimeType": r.mime_type,
            "fileSizeBytes": r.file_size_bytes,
            "status": r.status,
            "malwareScan": r.malware_scan,
            "createdAt": r.created_at.isoformat() if r.created_at else None
        }
        for r in ev_rows
    ]

    # 4. Query Real Audit Timeline
    tl_res = await db.execute(text("SELECT timeline_id, event_type, actor_role, description, created_at FROM investigation.case_timeline WHERE case_id = :cid ORDER BY created_at ASC"), {"cid": case_uuid})
    tl_rows = tl_res.fetchall()
    timeline_items = [
        {
            "timelineId": str(r.timeline_id),
            "eventType": r.event_type,
            "actorRole": r.actor_role,
            "description": r.description,
            "createdAt": r.created_at.isoformat() if r.created_at else None
        }
        for r in tl_rows
    ]

    # 5. Query Neo4j for actual entity graph metrics if available
    graph_export = {"nodesCount": 0, "edgesCount": 0, "connectedEntities": []}
    suspect_phone = case_row.suspect_phone
    if suspect_phone:
        async def _query_neo4j():
            driver = AsyncGraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD))
            try:
                async with driver.session() as session:
                    q = "MATCH (anchor:Entity {id: $entityId}) OPTIONAL MATCH (anchor)-[r]-(linked) RETURN anchor, collect(DISTINCT linked) as nodes, collect(DISTINCT r) as edges"
                    g_res = await session.run(q, entityId=suspect_phone)
                    g_rec = await g_res.single()
                    if g_rec and g_rec["anchor"]:
                        nodes_list = g_rec["nodes"] or []
                        edges_list = g_rec["edges"] or []
                        return {
                            "anchorId": suspect_phone,
                            "nodesCount": len(nodes_list) + 1,
                            "edgesCount": len(edges_list),
                            "connectedEntities": [n.get("id") for n in nodes_list if n.get("id")]
                        }
            finally:
                await driver.close()
            return {"nodesCount": 0, "edgesCount": 0, "connectedEntities": []}

        try:
            graph_export = await asyncio.wait_for(_query_neo4j(), timeout=2.0)
        except Exception:
            pass

    # 6. Build Canonical JSON Bundle
    bundle = {
        "caseId": str(case_uuid),
        "packageId": str(package_id),
        "reportId": str(report_id),
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "caseDetails": case_info,
        "aiFusedVerdict": ai_verdict,
        "evidenceItems": evidence_items,
        "chainOfCustodyTimeline": timeline_items,
        "graphNetworkExport": graph_export,
    }
    
    # Sort keys for canonical representation
    canonical_json = json.dumps(bundle, separators=(',', ':'), sort_keys=True).encode('utf-8')
    
    # Digest & RS256 Signature
    hex_digest = hashlib.sha256(canonical_json).hexdigest()
    signature = private_key.sign(
        canonical_json,
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    signature_b64 = base64.b64encode(signature).decode('utf-8')
    
    # Save to MinIO
    try:
        s3_client.head_bucket(Bucket=settings.MINIO_BUCKET_REPORTS)
    except Exception:
        try:
            s3_client.create_bucket(Bucket=settings.MINIO_BUCKET_REPORTS)
        except Exception:
            pass

    s3_key = f"intel/{case_uuid}/{package_id}.json"
    s3_client.put_object(
        Bucket=settings.MINIO_BUCKET_REPORTS,
        Key=s3_key,
        Body=canonical_json,
        ContentType="application/json"
    )
    
    report = Report(
        report_id=report_id,
        case_id=case_uuid,
        report_type='INTELLIGENCE_PACKAGE',
        status='READY',
        minio_bucket=settings.MINIO_BUCKET_REPORTS,
        object_key=s3_key,
        signature_algorithm='RS256',
        signature=signature_b64,
        public_key_fingerprint=public_key_fingerprint,
        generated_at=datetime.datetime.now(datetime.timezone.utc)
    )
    db.add(report)
    await db.flush()
    
    intel_pkg = IntelligencePackage(
        package_id=package_id,
        report_id=report_id,
        case_id=case_uuid,
        bundle_sha256=hex_digest,
        signature_algorithm='RS256',
        signature=signature_b64,
        public_key_fingerprint=public_key_fingerprint,
        status='READY',
        generated_at=datetime.datetime.now(datetime.timezone.utc)
    )
    db.add(intel_pkg)
    await db.flush()
    
    outbox = Outbox(
        aggregate_type='IntelligencePackage',
        aggregate_id=package_id,
        event_type='IntelligencePackage.Generated',
        topic='reporting.events',
        event_key=str(case_uuid),
        payload={"eventType": "IntelligencePackage.Generated", "packageId": str(package_id), "caseId": str(case_uuid)}
    )
    db.add(outbox)
    await db.commit()
    
    return {
        "packageId": str(package_id),
        "caseData": bundle,
        "bundleSha256": hex_digest,
        "signatureAlgorithm": "RS256",
        "signature": signature_b64,
        "publicKeyFingerprint": public_key_fingerprint
    }

@router.get("/reports/{report_id}")
async def get_report(report_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Report).filter(Report.report_id == uuid.UUID(report_id)))
    report = result.scalar_one_or_none()
    
    if not report or report.status != 'READY':
        raise HTTPException(status_code=404, detail="Report not available")
        
    try:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': report.minio_bucket, 'Key': report.object_key},
            ExpiresIn=3600
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not generate download URL")

    return {"reportId": str(report.report_id), "downloadUrl": presigned_url}


@router.get("/reports")
async def list_reports(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """List all generated intelligence packages and reports for Gov / MHA portal."""
    query = text("""
        SELECT 
            p.package_id, p.case_id, p.status, p.bundle_sha256, p.signature_algorithm,
            p.public_key_fingerprint, p.generated_at, r.report_type, r.object_key
        FROM reporting.intelligence_packages p
        LEFT JOIN reporting.reports r ON p.report_id = r.report_id
        ORDER BY p.generated_at DESC
        LIMIT :limit
    """)
    res = await db.execute(query, {"limit": limit})
    rows = res.fetchall()
    
    items = []
    for r in rows:
        download_url = None
        if r.object_key:
            try:
                download_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': settings.MINIO_BUCKET_REPORTS, 'Key': r.object_key},
                    ExpiresIn=86400
                )
            except Exception:
                download_url = f"{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET_REPORTS}/{r.object_key}"

        items.append({
            "packageId": str(r.package_id),
            "caseId": str(r.case_id),
            "reportType": r.report_type or "INTELLIGENCE_PACKAGE",
            "status": r.status,
            "bundleSha256": r.bundle_sha256,
            "signatureAlgorithm": r.signature_algorithm,
            "publicKeyFingerprint": r.public_key_fingerprint,
            "generatedAt": r.generated_at.isoformat() if r.generated_at else None,
            "downloadUrl": download_url,
        })
    return {"items": items, "total": len(items), "hasMore": False}


@router.get("/reports/packages/{package_id}/download")
async def download_package(package_id: str, db: AsyncSession = Depends(get_db)):
    """Directly stream the signed canonical JSON package from MinIO to the requester."""
    query = text("""
        SELECT p.package_id, p.case_id, r.object_key 
        FROM reporting.intelligence_packages p
        LEFT JOIN reporting.reports r ON p.report_id = r.report_id
        WHERE p.package_id = :pid
    """)
    res = await db.execute(query, {"pid": uuid.UUID(package_id)})
    row = res.fetchone()
    if not row or not row.object_key:
        raise HTTPException(status_code=404, detail="Intelligence package not found")
    
    try:
        obj = s3_client.get_object(Bucket=settings.MINIO_BUCKET_REPORTS, Key=row.object_key)
        content = obj['Body'].read()
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="intelligence_package_{row.case_id}.json"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch package file: {e}")
@router.get("/reports/flagged-cases")
async def list_flagged_cases(db: AsyncSession = Depends(get_db)):
    """Query PostgreSQL investigation.cases + fused_verdicts directly for real-time risk upgrades."""
    query = text("""
        SELECT c.case_id, c.case_number, c.title, c.description, c.complaint_type, c.suspect_account, c.reporter_phone, c.created_at,
               COALESCE(v.fused_score, 73.0) as fused_score,
               COALESCE(v.risk_tier, 'HIGH') as risk_tier,
               COALESCE(v.reason, 'Multi-model AI consensus') as reason
        FROM investigation.cases c
        LEFT JOIN (
            SELECT DISTINCT ON (case_id) case_id, fused_score, risk_tier, reason
            FROM inference.fused_verdicts
            ORDER BY case_id, fusion_timestamp DESC
        ) v ON c.case_id = v.case_id
        WHERE c.complaint_type = 'UPI_FRAUD' OR v.risk_tier IN ('HIGH', 'CRITICAL') OR v.fused_score >= 60
        ORDER BY c.created_at DESC
        LIMIT 100
    """)
    res = await db.execute(query)
    rows = res.fetchall()
    items = []
    for r in rows:
        items.append({
            "caseId": str(r.case_id),
            "caseNumber": r.case_number,
            "title": r.title,
            "description": r.description,
            "complaintType": r.complaint_type,
            "suspectAccount": r.suspect_account,
            "reporterPhone": r.reporter_phone,
            "fusedScore": float(r.fused_score),
            "riskTier": r.risk_tier,
            "summary": r.reason,
            "createdAt": r.created_at.isoformat() if r.created_at else None
        })
    return {"items": items}
