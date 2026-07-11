# Geospatial Intelligence Service — API Contract
**Service:** `geospatial` | **Port:** 8000 | **Owner:** Nilkanta | **Task:** T8d
**Internal only** — called by Investigator BFF. RBAC-scoped by `jurisdictionId`.

> See [_shared_contract.md](./_shared_contract.md) for envelope and health conventions.

---

## Data Model (PostGIS)

Table: `fraud_hotspot`
```sql
CREATE TABLE fraud_hotspot (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  jurisdiction_id VARCHAR(64) NOT NULL,
  location     GEOGRAPHY(POINT, 4326) NOT NULL,  -- WGS84
  incident_count INTEGER DEFAULT 1,
  risk_tier    VARCHAR(16) DEFAULT 'LOW',
  last_incident_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON fraud_hotspot USING GIST (location);
```

**How the layer is updated (Kafka consumer, <60s SLO — FR-13.4):**
Listens to `Case.Created` and `CounterfeitScan.Submitted`. Extracts `complaintLat`/`complaintLon` and executes:
```sql
INSERT INTO fraud_hotspot (jurisdiction_id, location, risk_tier, last_incident_at)
VALUES ($1, ST_MakePoint($lon, $lat), $riskTier, NOW())
ON CONFLICT (location_hash) DO UPDATE
  SET incident_count = fraud_hotspot.incident_count + 1,
      updated_at = NOW();
```

---

## Endpoints

### GET /geo/hotspots
Get crime hotspots within a bounding box. RBAC: response filtered to caller's `jurisdictionId`.

**Query params:**
- `bbox` (required): `minLon,minLat,maxLon,maxLat` (WGS84, comma-separated)
- `riskTier` (optional): filter `LOW|MEDIUM|HIGH|CRITICAL`
- `from` (optional): ISO8601 start date
- `to` (optional): ISO8601 end date

**Response 200 (GeoJSON FeatureCollection):**
```json
{
  "data": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [72.877, 19.076]},
        "properties": {
          "hotspotId": "uuid",
          "incidentCount": 47,
          "riskTier": "HIGH",
          "jurisdictionId": "JUR_MH_MUMBAI",
          "lastIncidentAt": "2026-07-11T11:30:00Z"
        }
      }
    ],
    "totalFeatures": 1,
    "generatedAt": "2026-07-11T12:00:00Z"
  }
}
```

**Errors:**
- `400 INVALID_BBOX` — malformed bounding box
- `403 JURISDICTION_MISMATCH` — bbox outside caller's authorized jurisdiction

---

### GET /geo/patrol-zones
Get recommended patrol zones by district code.

**Query params:** `district=<district_code>`

**Response 200:**
```json
{
  "data": {
    "district": "MH_MUMBAI",
    "patrolZones": [
      {
        "zoneId": "uuid",
        "name": "Andheri West High-Density Zone",
        "geometry": {"type": "Polygon", "coordinates": [...]},
        "incidentDensity": 12.4,
        "suggestedPatrolUnits": 3,
        "riskTier": "HIGH"
      }
    ]
  }
}
```

---

### POST /geo/export
Export geospatial layer as GeoJSON file (FR-13.5).

**Request:**
```json
{
  "bbox": "72.8,18.9,73.1,19.2",
  "format": "geojson",
  "from": "2026-07-01T00:00:00Z",
  "to": "2026-07-11T00:00:00Z"
}
```

**Response 202:** Returns a download URL (presigned MinIO link, 1h TTL).
```json
{
  "data": {
    "exportId": "uuid",
    "downloadUrl": "https://minio:9000/geo-exports/uuid.geojson?...",
    "expiresAt": "2026-07-11T13:00:00Z"
  }
}
```

---

## Events Published

| Event | Trigger |
|---|---|
| `GeoLayer.Updated` | After successful PostGIS upsert from Kafka consumer |
