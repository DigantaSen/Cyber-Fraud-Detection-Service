from sqlalchemy import Column, String, DateTime, func, BigInteger, Boolean, ForeignKey, JSON
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()

class Report(Base):
    __tablename__ = "reports"
    __table_args__ = {'schema': 'reporting'}

    report_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    case_id = Column(UUID(as_uuid=True), nullable=False)
    report_type = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default='GENERATING')
    minio_bucket = Column(String(128), nullable=False, default='reports')
    object_key = Column(String)
    signature_algorithm = Column(String(32))
    signature = Column(String)
    public_key_fingerprint = Column(String)
    generated_by = Column(UUID(as_uuid=True))
    generated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class IntelligencePackage(Base):
    __tablename__ = "intelligence_packages"
    __table_args__ = {'schema': 'reporting'}

    package_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    report_id = Column(UUID(as_uuid=True), ForeignKey('reporting.reports.report_id'), unique=True)
    case_id = Column(UUID(as_uuid=True), nullable=False)
    include_graph_export = Column(Boolean, nullable=False, default=True)
    include_audit_trail = Column(Boolean, nullable=False, default=True)
    bundle_sha256 = Column(String(64))
    signature_algorithm = Column(String(32), nullable=False, default='RS256')
    signature = Column(String)
    public_key_fingerprint = Column(String)
    status = Column(String(32), nullable=False, default='GENERATING')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    generated_at = Column(DateTime(timezone=True))

class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = {'schema': 'platform'}

    outbox_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    topic = Column(String(128), nullable=False)
    event_key = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default='PENDING')
    attempts = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True))
