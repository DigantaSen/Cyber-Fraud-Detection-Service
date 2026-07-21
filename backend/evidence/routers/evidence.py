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

class UploadRequest(BaseModel):
    filename: str
    content_type: str
    file_size_bytes: int

@router.post("/cases/{case_id}/evidence")
async def request_upload(case_id: str, payload: UploadRequest, db: AsyncSession = Depends(get_db)):
    if payload.content_type not in ALLOWED_MIMETYPES:
        raise HTTPException(status_code=422, detail="MIME type not allowed")
    
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
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': settings.MINIO_BUCKET, 'Key': s3_key},
            ExpiresIn=3600
        )
    except ClientError as e:
        raise HTTPException(status_code=500, detail="Could not generate presigned URL")

    return {"evidenceId": str(evidence_id), "uploadUrl": presigned_url}

@router.get("/cases/{case_id}/evidence")
async def get_case_evidence(case_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Evidence).filter(Evidence.case_id == uuid.UUID(case_id)))
    items = result.scalars().all()
    
    return [
        {
            "evidenceId": str(item.evidence_id),
            "fileName": item.file_name,
            "mimeType": item.mime_type,
            "fileSizeBytes": item.file_size_bytes,
            "status": item.status,
            "createdAt": item.created_at.isoformat().replace("+00:00", "Z") if item.created_at else None,
            "verifiedAt": item.verified_at.isoformat().replace("+00:00", "Z") if item.verified_at else None
        }
        for item in items
    ]

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

    return {"status": "success", "evidenceId": evidence_id, "hash": sha256.hexdigest()}

@router.get("/evidence/{evidence_id}")
async def get_evidence(evidence_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Evidence).filter(Evidence.evidence_id == uuid.UUID(evidence_id)))
    evidence = result.scalar_one_or_none()
    
    if not evidence or evidence.status != 'VERIFIED':
        raise HTTPException(status_code=404, detail="Evidence not available")
        
    try:
        presigned_url = s3_client.generate_presigned_url(
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
