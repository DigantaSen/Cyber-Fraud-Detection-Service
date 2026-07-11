-- ============================================================
-- Platform Primary DB — Init Script
-- Runs once when the postgres container first starts.
-- ============================================================

-- The official postgres image creates POSTGRES_USER and POSTGRES_DB before
-- executing this script. Do not recreate them here: doing so makes a clean
-- `docker compose up` fail with a duplicate role/database error.
-- This script therefore runs against POSTGRES_DB as POSTGRES_USER.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO CURRENT_USER;
