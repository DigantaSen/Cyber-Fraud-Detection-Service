import uuid
import json
import hashlib
import base64
import datetime
import boto3
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

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

# RS256 Key Pair Mock (Vault fallback)
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
    case_id: str

class IntelPackageRequest(BaseModel):
    case_id: str

@router.post("/reports/ncrb")
async def generate_ncrb_report(payload: NCRBRequest, db: AsyncSession = Depends(get_db)):
    report_id = uuid.uuid4()
    case_uuid = uuid.UUID(payload.case_id)
    
    # Mock NCRB Report JSON
    ncrb_content = {
        "reportId": str(report_id),
        "caseId": str(case_uuid),
        "type": "NCRB_ANNUAL_CRIME",
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "READY",
        "summary": "Simulated NCRB report for hackathon."
    }
    content_bytes = json.dumps(ncrb_content, separators=(',', ':')).encode('utf-8')
    s3_key = f"ncrb/{case_uuid}/{report_id}.json"
    
    # Upload to MinIO
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
    
    # Outbox Event
    outbox = Outbox(
        topic='reporting.events',
        event_key=str(case_uuid),
        payload={"eventType": "Report.Generated", "reportId": str(report_id), "caseId": str(case_uuid)}
    )
    db.add(outbox)
    await db.commit()
    
    return {"reportId": str(report_id), "status": "READY"}

@router.post("/reports/intelligence-package")
async def generate_intel_package(payload: IntelPackageRequest, db: AsyncSession = Depends(get_db)):
    report_id = uuid.uuid4()
    package_id = uuid.uuid4()
    case_uuid = uuid.UUID(payload.case_id)
    
    # 1. Build Canonical JSON Bundle
    # In reality, this would query Neo4j, Evidence hashes, etc.
    bundle = {
        "caseId": str(case_uuid),
        "packageId": str(package_id),
        "evidenceHashes": [{"id": "mock-ev-1", "hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}],
        "neo4jGraphExport": {"nodes": 10, "edges": 15},
        "aiAuditTrail": ["ScamNLP: RISK_HIGH", "AudioAnalyzer: VOICE_CLONE_DETECTED"],
        "chainOfCustody": ["Uploaded by Citizen", "Verified by Platform", "Packaged by Intelligence Service"]
    }
    
    # Sort keys for canonical representation
    canonical_json = json.dumps(bundle, separators=(',', ':'), sort_keys=True).encode('utf-8')
    
    # 2. Compute SHA-256 Digest
    digest = hashlib.sha256(canonical_json).digest()
    hex_digest = hashlib.sha256(canonical_json).hexdigest()
    
    # 3. Sign the Digest using RS256
    signature = private_key.sign(
        canonical_json,
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    signature_b64 = base64.b64encode(signature).decode('utf-8')
    
    # 4. Save the bundle
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
        topic='reporting.events',
        event_key=str(case_uuid),
        payload={"eventType": "IntelligencePackage.Generated", "packageId": str(package_id), "caseId": str(case_uuid)}
    )
    db.add(outbox)
    await db.commit()
    
    return {
        "packageId": str(package_id),
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
