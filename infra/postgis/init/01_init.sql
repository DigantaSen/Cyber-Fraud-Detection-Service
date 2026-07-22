-- ============================================================
-- PostGIS Container — Init Script
-- Mounted into postgis:/docker-entrypoint-initdb.d/
-- The postgis/postgis:16-3.4 image already has PostGIS installed.
-- ============================================================

-- The postgis image inherits the official postgres entrypoint, which creates
-- POSTGRES_USER and POSTGRES_DB before processing this script. Keeping this
-- script schema-only makes it work with both default and overridden .env
-- credentials.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

GRANT ALL ON SCHEMA public TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO CURRENT_USER;
