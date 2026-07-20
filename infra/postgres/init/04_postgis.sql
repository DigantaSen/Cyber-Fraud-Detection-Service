CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE fraud_hotspot (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  jurisdiction_id VARCHAR(64) NOT NULL,
  geom GEOMETRY(Point, 4326) NOT NULL,
  location_hash VARCHAR(96) NOT NULL,
  incident_count INTEGER NOT NULL DEFAULT 1 CHECK (incident_count > 0),
  risk_tier VARCHAR(16) NOT NULL DEFAULT 'LOW' CHECK (risk_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  source_case_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  last_incident_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (jurisdiction_id, location_hash)
);

CREATE INDEX fraud_hotspot_geom_gix ON fraud_hotspot USING GIST (geom);
CREATE INDEX fraud_hotspot_jurisdiction_idx ON fraud_hotspot (jurisdiction_id, updated_at DESC);

CREATE TABLE patrol_zone (
  zone_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  jurisdiction_id VARCHAR(64) NOT NULL,
  district_code VARCHAR(64) NOT NULL,
  name VARCHAR(200) NOT NULL,
  geom GEOMETRY(Polygon, 4326) NOT NULL,
  incident_density NUMERIC(8,2) NOT NULL DEFAULT 0,
  suggested_patrol_units INTEGER NOT NULL DEFAULT 0,
  risk_tier VARCHAR(16) NOT NULL DEFAULT 'LOW' CHECK (risk_tier IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX patrol_zone_geom_gix ON patrol_zone USING GIST (geom);
CREATE INDEX patrol_zone_district_idx ON patrol_zone (district_code, risk_tier);

CREATE TABLE geo_export (
  export_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  requested_by UUID,
  jurisdiction_id VARCHAR(64) NOT NULL,
  bbox GEOMETRY(Polygon, 4326) NOT NULL,
  format VARCHAR(16) NOT NULL DEFAULT 'geojson',
  object_key TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Hotspot upsert used by the Kafka consumer:
-- INSERT INTO fraud_hotspot (
--   jurisdiction_id,
--   geom,
--   location_hash,
--   risk_tier,
--   source_case_ids,
--   last_incident_at
-- )
-- VALUES (
--   $1,
--   ST_SetSRID(ST_MakePoint($2, $3), 4326),
--   $4,
--   $5,
--   ARRAY[$6::uuid],
--   NOW()
-- )
-- ON CONFLICT (jurisdiction_id, location_hash)
-- DO UPDATE SET
--   incident_count = fraud_hotspot.incident_count + 1,
--   risk_tier = EXCLUDED.risk_tier,
--   source_case_ids = array_append(fraud_hotspot.source_case_ids, $6::uuid),
--   last_incident_at = NOW(),
--   updated_at = NOW();
