CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS investigation;
CREATE SCHEMA IF NOT EXISTS evidence;
CREATE SCHEMA IF NOT EXISTS notification;
CREATE SCHEMA IF NOT EXISTS inference;
CREATE SCHEMA IF NOT EXISTS reporting;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS platform;

CREATE OR REPLACE FUNCTION platform.set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION platform.prevent_mutation()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'append-only table % cannot be updated or deleted', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE identity.roles (
  role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(64) NOT NULL UNIQUE CHECK (
    name IN ('CITIZEN','INVESTIGATOR','BANK_OFFICIAL','TELECOM_ADMIN','GOV_OFFICIAL','ADMIN')
  ),
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE identity.users (
  user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(320) NOT NULL,
  password_hash TEXT NOT NULL,
  phone VARCHAR(20),
  role VARCHAR(64) NOT NULL REFERENCES identity.roles(name),
  org_id UUID,
  jurisdiction_id VARCHAR(64),
  mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  mfa_secret_enc TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SOFT_LOCKED','DISABLED')),
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (phone IS NULL OR phone ~ '^\+[1-9][0-9]{7,14}$'),
  CHECK (role = 'CITIZEN' OR jurisdiction_id IS NOT NULL)
);

CREATE UNIQUE INDEX users_email_lower_uidx ON identity.users (LOWER(email));
CREATE INDEX users_role_idx ON identity.users (role);
CREATE INDEX users_jurisdiction_idx ON identity.users (jurisdiction_id);

CREATE TRIGGER users_set_updated_at
BEFORE UPDATE ON identity.users
FOR EACH ROW EXECUTE FUNCTION platform.set_updated_at();

CREATE TABLE identity.sessions (
  session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES identity.users(user_id),
  refresh_token_hash TEXT NOT NULL UNIQUE,
  user_agent TEXT,
  ip_address INET,
  revoked_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX sessions_user_idx ON identity.sessions (user_id, expires_at DESC);
CREATE INDEX sessions_active_idx ON identity.sessions (expires_at) WHERE revoked_at IS NULL;

CREATE TABLE platform.idempotency_keys (
  idempotency_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service_name VARCHAR(64) NOT NULL,
  idempotency_key UUID NOT NULL,
  request_hash TEXT NOT NULL,
  response_status INTEGER,
  response_body JSONB,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (service_name, idempotency_key)
);

CREATE INDEX idempotency_expiry_idx ON platform.idempotency_keys (expires_at);

CREATE TABLE investigation.cases (
  case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_number VARCHAR(32) NOT NULL UNIQUE,
  title VARCHAR(200) NOT NULL,
  description TEXT NOT NULL,
  notes TEXT,
  complaint_type VARCHAR(32) NOT NULL CHECK (
    complaint_type IN ('UPI_FRAUD','CALL_FRAUD','COUNTERFEIT_CURRENCY','CYBER_CRIME','OTHER')
  ),
  suspect_phone VARCHAR(20),
  suspect_account VARCHAR(64),
  complaint_lat NUMERIC(9,6),
  complaint_lon NUMERIC(9,6),
  reporter_user_id UUID REFERENCES identity.users(user_id),
  reporter_entity_name VARCHAR(200),
  reporter_phone VARCHAR(20),
  language_code VARCHAR(16) NOT NULL DEFAULT 'en',
  jurisdiction_id VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'New' CHECK (
    status IN ('New','Assigned','Investigating','Pending_AI','Action_Taken','Closed')
  ),
  assigned_investigator UUID REFERENCES identity.users(user_id),
  priority VARCHAR(16) NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('LOW','NORMAL','HIGH','CRITICAL')),
  disposition VARCHAR(64),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (suspect_phone IS NULL OR suspect_phone ~ '^\+[1-9][0-9]{7,14}$'),
  CHECK (reporter_phone IS NULL OR reporter_phone ~ '^\+[1-9][0-9]{7,14}$'),
  CHECK (complaint_lat IS NULL OR complaint_lat BETWEEN -90 AND 90),
  CHECK (complaint_lon IS NULL OR complaint_lon BETWEEN -180 AND 180)
);

CREATE INDEX cases_status_created_idx ON investigation.cases (status, created_at DESC);
CREATE INDEX cases_jurisdiction_idx ON investigation.cases (jurisdiction_id, created_at DESC);
CREATE INDEX cases_assigned_idx ON investigation.cases (assigned_investigator, created_at DESC);
CREATE INDEX cases_reporter_idx ON investigation.cases (reporter_user_id, created_at DESC);

CREATE TRIGGER cases_set_updated_at
BEFORE UPDATE ON investigation.cases
FOR EACH ROW EXECUTE FUNCTION platform.set_updated_at();

CREATE TABLE investigation.case_timeline (
  timeline_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES investigation.cases(case_id),
  event_type VARCHAR(128) NOT NULL,
  actor_id UUID,
  actor_role VARCHAR(64),
  description TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  correlation_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX case_timeline_case_created_idx ON investigation.case_timeline (case_id, created_at DESC);

CREATE TABLE evidence.evidence (
  evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES investigation.cases(case_id),
  file_name VARCHAR(255) NOT NULL,
  mime_type VARCHAR(128) NOT NULL CHECK (
    mime_type IN ('image/png','image/jpeg','application/pdf','audio/wav','audio/mpeg','audio/m4a','audio/ogg')
  ),
  file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0 AND file_size_bytes <= 52428800),
  minio_bucket VARCHAR(128) NOT NULL DEFAULT 'evidence',
  object_key TEXT NOT NULL UNIQUE,
  status VARCHAR(32) NOT NULL DEFAULT 'PENDING_UPLOAD' CHECK (
    status IN ('PENDING_UPLOAD','UPLOADED','VERIFIED','CORRUPT','REJECTED')
  ),
  malware_scan VARCHAR(32) DEFAULT 'PENDING',
  uploaded_by UUID REFERENCES identity.users(user_id),
  upload_url_expires_at TIMESTAMPTZ,
  verified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX evidence_case_idx ON evidence.evidence (case_id, created_at DESC);
CREATE INDEX evidence_status_idx ON evidence.evidence (status);

CREATE TRIGGER evidence_set_updated_at
BEFORE UPDATE ON evidence.evidence
FOR EACH ROW EXECUTE FUNCTION platform.set_updated_at();

CREATE TABLE evidence.evidence_hash (
  evidence_hash_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_id UUID NOT NULL UNIQUE REFERENCES evidence.evidence(evidence_id),
  algorithm VARCHAR(16) NOT NULL DEFAULT 'SHA-256',
  client_sha256 CHAR(64),
  sha256 CHAR(64) NOT NULL,
  hash_match BOOLEAN NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  CHECK (client_sha256 IS NULL OR client_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE notification.notifications (
  notification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES identity.users(user_id),
  case_id UUID REFERENCES investigation.cases(case_id),
  channel VARCHAR(16) NOT NULL CHECK (channel IN ('SMS','EMAIL','PUSH','SSE')),
  template_id VARCHAR(128) NOT NULL,
  variables JSONB NOT NULL DEFAULT '{}'::jsonb,
  priority VARCHAR(16) NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('NORMAL','HIGH','CRITICAL')),
  status VARCHAR(32) NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED','SENT','DELIVERED','FAILED')),
  error_message TEXT,
  queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  sent_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ
);

CREATE INDEX notifications_user_idx ON notification.notifications (user_id, queued_at DESC);
CREATE INDEX notifications_case_idx ON notification.notifications (case_id, queued_at DESC);
CREATE INDEX notifications_status_idx ON notification.notifications (status, priority);

CREATE TABLE notification.notification_preferences (
  user_id UUID PRIMARY KEY REFERENCES identity.users(user_id),
  sms_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  email_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  push_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  quiet_hours_start TIME,
  quiet_hours_end TIME,
  language VARCHAR(16) NOT NULL DEFAULT 'en',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE notification.mha_alerts (
  alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID REFERENCES investigation.cases(case_id),
  alert_type VARCHAR(64) NOT NULL,
  risk_tier VARCHAR(16) NOT NULL CHECK (risk_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  summary TEXT NOT NULL,
  suspects JSONB NOT NULL DEFAULT '[]'::jsonb,
  jurisdiction_id VARCHAR(64) NOT NULL,
  triggered_by UUID,
  webhook_url TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'DISPATCHED' CHECK (status IN ('DISPATCHED','FAILED')),
  delivery_latency_ms INTEGER,
  dispatched_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX mha_alerts_jurisdiction_idx ON notification.mha_alerts (jurisdiction_id, created_at DESC);
CREATE INDEX mha_alerts_case_idx ON notification.mha_alerts (case_id);

CREATE TABLE inference.predictions (
  prediction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES investigation.cases(case_id),
  trigger_type VARCHAR(32) NOT NULL CHECK (
    trigger_type IN ('CASE_CREATED','EVIDENCE_UPLOADED','TELECOM_EVENT','BANK_TRANSACTION')
  ),
  status VARCHAR(32) NOT NULL DEFAULT 'PROCESSING' CHECK (status IN ('PROCESSING','COMPLETE','FAILED')),
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  correlation_id UUID
);

CREATE INDEX predictions_case_requested_idx ON inference.predictions (case_id, requested_at DESC);

CREATE TABLE inference.fused_verdicts (
  prediction_id UUID PRIMARY KEY REFERENCES inference.predictions(prediction_id),
  case_id UUID NOT NULL REFERENCES investigation.cases(case_id),
  fused_score NUMERIC(5,2) NOT NULL CHECK (fused_score BETWEEN 0 AND 100),
  risk_tier VARCHAR(16) NOT NULL CHECK (risk_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  confidence NUMERIC(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  status VARCHAR(32) NOT NULL CHECK (status IN ('COMPLETE','INCOMPLETE','PENDING_REVIEW')),
  model_breakdown JSONB NOT NULL DEFAULT '[]'::jsonb,
  explanation TEXT NOT NULL,
  fusion_weights JSONB NOT NULL,
  pending_review BOOLEAN NOT NULL DEFAULT FALSE,
  pending_notification BOOLEAN NOT NULL DEFAULT FALSE,
  fusion_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  correlation_id UUID
);

CREATE INDEX fused_verdicts_case_idx ON inference.fused_verdicts (case_id, fusion_timestamp DESC);
CREATE INDEX fused_verdicts_review_idx ON inference.fused_verdicts (pending_review, fusion_timestamp DESC);

CREATE TRIGGER fused_verdicts_append_only
BEFORE UPDATE OR DELETE ON inference.fused_verdicts
FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();

CREATE TABLE inference.override_records (
  override_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES investigation.cases(case_id),
  original_verdict_id UUID NOT NULL REFERENCES inference.fused_verdicts(prediction_id),
  decision VARCHAR(16) NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
  justification TEXT NOT NULL CHECK (LENGTH(justification) >= 20),
  investigator_id UUID NOT NULL REFERENCES identity.users(user_id),
  original_score NUMERIC(5,2),
  original_confidence NUMERIC(4,3),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  correlation_id UUID
);

CREATE INDEX override_case_idx ON inference.override_records (case_id, created_at DESC);
CREATE INDEX override_investigator_idx ON inference.override_records (investigator_id, created_at DESC);

CREATE TRIGGER override_records_append_only
BEFORE UPDATE OR DELETE ON inference.override_records
FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();

CREATE TABLE reporting.reports (
  report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES investigation.cases(case_id),
  report_type VARCHAR(64) NOT NULL CHECK (report_type IN ('NCRB_ANNUAL_CRIME','INTELLIGENCE_PACKAGE')),
  status VARCHAR(32) NOT NULL DEFAULT 'GENERATING' CHECK (status IN ('GENERATING','READY','FAILED')),
  minio_bucket VARCHAR(128) NOT NULL DEFAULT 'reports',
  object_key TEXT,
  signature_algorithm VARCHAR(32),
  signature TEXT,
  public_key_fingerprint TEXT,
  generated_by UUID REFERENCES identity.users(user_id),
  generated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX reports_case_idx ON reporting.reports (case_id, created_at DESC);
CREATE INDEX reports_status_idx ON reporting.reports (status, created_at DESC);

CREATE TRIGGER reports_set_updated_at
BEFORE UPDATE ON reporting.reports
FOR EACH ROW EXECUTE FUNCTION platform.set_updated_at();

CREATE TABLE reporting.intelligence_packages (
  package_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id UUID UNIQUE REFERENCES reporting.reports(report_id),
  case_id UUID NOT NULL REFERENCES investigation.cases(case_id),
  include_graph_export BOOLEAN NOT NULL DEFAULT TRUE,
  include_audit_trail BOOLEAN NOT NULL DEFAULT TRUE,
  bundle_sha256 CHAR(64),
  signature_algorithm VARCHAR(32) NOT NULL DEFAULT 'RS256',
  signature TEXT,
  public_key_fingerprint TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'GENERATING' CHECK (status IN ('GENERATING','READY','FAILED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  generated_at TIMESTAMPTZ
);

CREATE INDEX intelligence_packages_case_idx ON reporting.intelligence_packages (case_id, created_at DESC);

CREATE TABLE audit.audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type VARCHAR(128) NOT NULL,
  entity_type VARCHAR(64) NOT NULL,
  entity_id UUID NOT NULL,
  actor_id UUID,
  actor_role VARCHAR(64),
  payload JSONB NOT NULL,
  correlation_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX audit_entity_idx ON audit.audit_log (entity_id, created_at DESC);
CREATE INDEX audit_event_idx ON audit.audit_log (event_type, created_at DESC);
CREATE INDEX audit_correlation_idx ON audit.audit_log (correlation_id);

CREATE TRIGGER audit_log_append_only
BEFORE UPDATE OR DELETE ON audit.audit_log
FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();

CREATE TABLE platform.outbox (
  outbox_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  aggregate_type VARCHAR(64) NOT NULL,
  aggregate_id UUID NOT NULL,
  event_type VARCHAR(128) NOT NULL,
  topic VARCHAR(128) NOT NULL,
  event_key TEXT NOT NULL,
  payload JSONB NOT NULL,
  correlation_id UUID,
  status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PUBLISHED','FAILED')),
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX outbox_pending_idx ON platform.outbox (status, created_at) WHERE status = 'PENDING';
CREATE INDEX outbox_aggregate_idx ON platform.outbox (aggregate_type, aggregate_id);

CREATE OR REPLACE FUNCTION platform.notify_outbox()
RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('outbox_channel', NEW.outbox_id::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER outbox_notify_after_insert
AFTER INSERT ON platform.outbox
FOR EACH ROW EXECUTE FUNCTION platform.notify_outbox();
