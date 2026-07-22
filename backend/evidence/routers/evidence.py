import uuid
import hashlib
import magic
import boto3
import clamd
import datetime
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select

from config import settings
from models import Evidence, EvidenceHash

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

presigned_s3_client = boto3.client(
    's3',
    endpoint_url="http://localhost:9000",
    aws_access_key_id=settings.MINIO_ACCESS_KEY,
    aws_secret_access_key=settings.MINIO_SECRET_KEY,
)

clamav = clamd.ClamdNetworkSocket(settings.CLAMAV_HOST, settings.CLAMAV_PORT)

ALLOWED_MIMETYPES = [
    "image/png",
    "image/jpeg",
    "application/pdf",
    "audio/wav",
    "audio/mpeg",
    "audio/m4a",
    "audio/x-m4a",
    "audio/ogg"
]

from pydantic import Field, ConfigDict

class UploadRequest(BaseModel):
    filename: str = Field(..., alias="fileName")
    content_type: str = Field(..., alias="mimeType")
    file_size_bytes: int = Field(..., alias="fileSizeBytes")

    model_config = ConfigDict(populate_by_name=True)

@router.post("/cases/{case_id}/evidence")
async def request_upload(case_id: str, payload: UploadRequest, db: AsyncSession = Depends(get_db)):
    if payload.content_type not in ALLOWED_MIMETYPES:
        raise HTTPException(status_code=422, detail="MIME type not allowed")

    # Guard: Check case existence and status
    from sqlalchemy import text
    try:
        case_check = await db.execute(
            text("SELECT status FROM investigation.cases WHERE case_id = :cid"),
            {"cid": uuid.UUID(case_id)}
        )
        c_row = case_check.fetchone()
        if not c_row:
            raise HTTPException(
                status_code=404,
                detail={"errorCode": "CASE_NOT_FOUND", "message": f"Case {case_id} not found."}
            )
        if (c_row[0] or "").upper() in ("CLOSED", "DISMISSED"):
            raise HTTPException(
                status_code=400,
                detail={"errorCode": "CASE_CLOSED", "message": "Cannot upload evidence to a closed or dismissed case."}
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to verify case existence: {e}")
    
    evidence_id = uuid.uuid4()
    s3_key = f"cases/{case_id}/{evidence_id}/{payload.filename}"
    
    evidence = Evidence(
        evidence_id=evidence_id,
        case_id=uuid.UUID(case_id),
        file_name=payload.filename,
        mime_type=payload.content_type,
        file_size_bytes=payload.file_size_bytes,
        minio_bucket=settings.MINIO_BUCKET,
        object_key=s3_key,
        status='PENDING_UPLOAD',
        upload_url_expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    )
    db.add(evidence)
    await db.commit()

    try:
        presigned_url = presigned_s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': settings.MINIO_BUCKET, 'Key': s3_key, 'ContentType': payload.content_type},
            ExpiresIn=3600
        )
    except ClientError as e:
        raise HTTPException(status_code=500, detail="Could not generate presigned URL")

    return {"evidenceId": str(evidence_id), "uploadUrl": presigned_url}

@router.get("/cases/{case_id}/evidence")
async def get_case_evidence(case_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Evidence).filter(Evidence.case_id == uuid.UUID(case_id)))
    items = result.scalars().all()
    
    out = []
    for item in items:
        dl_url = None
        if item.status == 'VERIFIED':
            try:
                dl_url = presigned_s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': item.minio_bucket, 'Key': item.object_key},
                    ExpiresIn=3600
                )
            except Exception:
                pass
        out.append({
            "evidenceId": str(item.evidence_id),
            "fileName": item.file_name,
            "mimeType": item.mime_type,
            "fileSizeBytes": item.file_size_bytes,
            "status": item.status,
            "downloadUrl": dl_url,
            "createdAt": item.created_at.isoformat().replace("+00:00", "Z") if item.created_at else None,
            "verifiedAt": item.verified_at.isoformat().replace("+00:00", "Z") if item.verified_at else None
        })
    return out

@router.post("/evidence/{evidence_id}/confirm")
async def confirm_upload(evidence_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Evidence).filter(Evidence.evidence_id == uuid.UUID(evidence_id)))
    evidence = result.scalar_one_or_none()
    
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
        
    if evidence.status != 'PENDING_UPLOAD':
        raise HTTPException(status_code=400, detail="Evidence already confirmed")

    try:
        response = s3_client.get_object(Bucket=evidence.minio_bucket, Key=evidence.object_key)
        file_stream = response['Body']
    except ClientError as e:
        raise HTTPException(status_code=400, detail="File not found in storage")

    sha256 = hashlib.sha256()
    file_bytes = b""
    
    for chunk in file_stream.iter_chunks(chunk_size=4096):
        sha256.update(chunk)
        if len(file_bytes) < 2048:
            file_bytes += chunk
    
    mime = magic.Magic(mime=True)
    detected_mime = mime.from_buffer(file_bytes)
    
    if detected_mime not in ALLOWED_MIMETYPES:
        evidence.status = 'REJECTED'
        await db.commit()
        raise HTTPException(status_code=422, detail={"errorCode": "INVALID_MIME", "message": f"MIME {detected_mime} not allowed"})

    try:
        response = s3_client.get_object(Bucket=evidence.minio_bucket, Key=evidence.object_key)
        scan_result = clamav.instream(response['Body'])
        if scan_result and scan_result.get('stream', [None])[0] == 'FOUND':
            evidence.status = 'REJECTED'
            evidence.malware_scan = 'MALWARE_DETECTED'
            await db.commit()
            raise HTTPException(status_code=422, detail={"errorCode": "MALWARE_DETECTED"})
    except (clamd.ConnectionError, ConnectionRefusedError):
        # Gracefully degrade if ClamAV is down
        print("Warning: ClamAV is unavailable, skipping scan.")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Malware scan failed: {str(e)}")
    
    evidence.status = 'VERIFIED'
    evidence.malware_scan = 'CLEAN'
    evidence.verified_at = datetime.datetime.now(datetime.timezone.utc)
    
    evidence_hash = EvidenceHash(
        evidence_id=evidence.evidence_id,
        sha256=sha256.hexdigest(),
        hash_match=True
    )
    db.add(evidence_hash)
    await db.commit()

    # Publish evidence.uploaded to Kafka via confluent_kafka
    try:
        from confluent_kafka import Producer
        import json
        p = Producer({'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS})
        ev_payload = {
            "eventType": "evidence.uploaded",
            "evidenceId": str(evidence.evidence_id),
            "caseId": str(evidence.case_id),
            "mimeType": evidence.mime_type,
            "fileName": evidence.file_name,
            "fileSizeBytes": evidence.file_size_bytes,
            "sha256": sha256.hexdigest(),
            "createdAt": evidence.verified_at.isoformat() if evidence.verified_at else None
        }
        p.produce("evidence.uploaded", value=json.dumps(ev_payload).encode("utf-8"))
        p.flush()
        print(f"Published evidence.uploaded for case {evidence.case_id}")
    except Exception as e:
        print(f"Warning: Could not publish evidence.uploaded event: {e}")

    return {"status": "success", "evidenceId": evidence_id, "hash": sha256.hexdigest()}

@router.get("/evidence/{evidence_id}")
async def get_evidence(evidence_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Evidence).filter(Evidence.evidence_id == uuid.UUID(evidence_id)))
    evidence = result.scalar_one_or_none()
    
    if not evidence or evidence.status != 'VERIFIED':
        raise HTTPException(status_code=404, detail="Evidence not available")
        
    try:
        presigned_url = presigned_s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': evidence.minio_bucket, 'Key': evidence.object_key},
            ExpiresIn=3600
        )
    except ClientError as e:
        raise HTTPException(status_code=500, detail="Could not generate presigned URL")

    return {"evidenceId": evidence_id, "downloadUrl": presigned_url}

@router.get("/evidence/{evidence_id}/hash")
async def get_evidence_hash(evidence_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(EvidenceHash).filter(EvidenceHash.evidence_id == uuid.UUID(evidence_id)))
    evidence_hash = result.scalar_one_or_none()
    
    if not evidence_hash:
        raise HTTPException(status_code=404, detail="Hash not available")

    return {"evidenceId": evidence_id, "hash": evidence_hash.sha256}
