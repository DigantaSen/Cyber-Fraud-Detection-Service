from sqlalchemy import Column, String, DateTime, func, BigInteger, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()

class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = {'schema': 'evidence'}

    evidence_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    case_id = Column(UUID(as_uuid=True), nullable=False)
    file_name = Column(String(255), nullable=False)
    mime_type = Column(String(128), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)
    minio_bucket = Column(String(128), nullable=False, default='evidence')
    object_key = Column(String, nullable=False, unique=True)
    status = Column(String(32), nullable=False, default='PENDING_UPLOAD')
    malware_scan = Column(String(32), default='PENDING')
    uploaded_by = Column(UUID(as_uuid=True), nullable=True)
    upload_url_expires_at = Column(DateTime(timezone=True))
    verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class EvidenceHash(Base):
    __tablename__ = "evidence_hash"
    __table_args__ = {'schema': 'evidence'}

    evidence_hash_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    evidence_id = Column(UUID(as_uuid=True), ForeignKey('evidence.evidence.evidence_id'), nullable=False, unique=True)
    algorithm = Column(String(16), nullable=False, default='SHA-256')
    client_sha256 = Column(String(64))
    sha256 = Column(String(64), nullable=False)
    hash_match = Column(Boolean, nullable=False)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())
