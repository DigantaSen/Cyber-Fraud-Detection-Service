import json
import uuid
import tempfile
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from minio import Minio

from response_helpers import success_response, error_response

router = APIRouter(prefix="/geo", tags=["Geospatial"])


class ExportRequest(BaseModel):
    bbox: str
    format: str = "geojson"
    from_date: Optional[str] = Query(None, alias="from")
    to_date: Optional[str] = Query(None, alias="to")


def get_jurisdiction(request: Request) -> str:
    ctx_str = request.headers.get("X-User-Context")
    if ctx_str:
        try:
            ctx = json.loads(ctx_str)
            return ctx.get("jurisdictionId", "")
        except:
            pass
    return ""


@router.get("/hotspots")
async def get_hotspots(
    request: Request,
    bbox: str = Query(...),
    riskTier: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to")
):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    jurisdiction_id = get_jurisdiction(request)
    
    if not jurisdiction_id:
        return JSONResponse(status_code=403, content=error_response("JURISDICTION_MISSING", "Jurisdiction ID is required", correlation_id))

    try:
        coords = [float(x) for x in bbox.split(",")]
        if len(coords) != 4:
            raise ValueError()
        min_lon, min_lat, max_lon, max_lat = coords
    except ValueError:
        return JSONResponse(status_code=400, content=error_response("INVALID_BBOX", "bbox must be minLon,minLat,maxLon,maxLat", correlation_id))

    db = request.app.state.db

    # PostGIS bounding box intersection using ST_MakeEnvelope
    query = """
    SELECT
        id,
        incident_count,
        risk_tier,
        jurisdiction_id,
        last_incident_at,
        ST_X(geom::geometry) AS lon,
        ST_Y(geom::geometry) AS lat
    FROM fraud_hotspot
    WHERE jurisdiction_id = $1
      AND geom && ST_MakeEnvelope($2, $3, $4, $5, 4326)
    """
    
    params = [jurisdiction_id, min_lon, min_lat, max_lon, max_lat]
    
    if riskTier:
        query += " AND risk_tier = $" + str(len(params) + 1)
        params.append(riskTier)

    async with db.acquire() as conn:
        rows = await conn.fetch(query, *params)
        
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "hotspotId": str(r["id"]),
                "incidentCount": r["incident_count"],
                "riskTier": r["risk_tier"],
                "jurisdictionId": r["jurisdiction_id"],
                "lastIncidentAt": r["last_incident_at"].isoformat() if r["last_incident_at"] else None
            }
        })
        
    response_data = {
        "type": "FeatureCollection",
        "features": features,
        "totalFeatures": len(features),
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
    
    return success_response(response_data, correlation_id)


@router.get("/patrol-zones")
async def get_patrol_zones(
    request: Request,
    district: str = Query(...)
):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    jurisdiction_id = get_jurisdiction(request)
    
    db = request.app.state.db
    
    query = """
    SELECT
        zone_id,
        name,
        incident_density,
        suggested_patrol_units,
        risk_tier,
        ST_AsGeoJSON(geom) AS geom_json
    FROM patrol_zone
    WHERE district_code = $1 AND jurisdiction_id = $2
    """
    
    async with db.acquire() as conn:
        rows = await conn.fetch(query, district, jurisdiction_id)
        
    zones = []
    for r in rows:
        zones.append({
            "zoneId": str(r["zone_id"]),
            "name": r["name"],
            "geometry": json.loads(r["geom_json"]),
            "incidentDensity": float(r["incident_density"]),
            "suggestedPatrolUnits": r["suggested_patrol_units"],
            "riskTier": r["risk_tier"]
        })
        
    return success_response({
        "district": district,
        "patrolZones": zones
    }, correlation_id)


@router.post("/export")
async def export_geo(
    request: Request,
    payload: ExportRequest
):
    correlation_id = request.headers.get("X-Correlation-ID", "")
    jurisdiction_id = get_jurisdiction(request)
    db = request.app.state.db
    minio_client: Minio = request.app.state.minio
    
    try:
        coords = [float(x) for x in payload.bbox.split(",")]
        if len(coords) != 4:
            raise ValueError()
        min_lon, min_lat, max_lon, max_lat = coords
    except ValueError:
        return JSONResponse(status_code=400, content=error_response("INVALID_BBOX", "bbox must be minLon,minLat,maxLon,maxLat", correlation_id))

    query = """
    SELECT ST_AsGeoJSON(geom) AS geom_json, id, incident_count, risk_tier, last_incident_at
    FROM fraud_hotspot
    WHERE jurisdiction_id = $1
      AND geom && ST_MakeEnvelope($2, $3, $4, $5, 4326)
    """
    
    async with db.acquire() as conn:
        rows = await conn.fetch(query, jurisdiction_id, min_lon, min_lat, max_lon, max_lat)
        
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geom_json"]),
            "properties": {
                "hotspotId": str(r["id"]),
                "incidentCount": r["incident_count"],
                "riskTier": r["risk_tier"],
                "lastIncidentAt": r["last_incident_at"].isoformat() if r["last_incident_at"] else None
            }
        })
        
    fc = {
        "type": "FeatureCollection",
        "features": features
    }
    
    export_id = str(uuid.uuid4())
    object_key = f"{export_id}.geojson"
    
    # Save to temp file
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_f:
        json.dump(fc, temp_f)
        temp_path = temp_f.name
        
    # Upload to MinIO
    minio_client.fput_object("geo-exports", object_key, temp_path, content_type="application/geo+json")
    os.remove(temp_path)
    
    # Generate presigned URL (1h TTL)
    url = minio_client.presigned_get_object("geo-exports", object_key, expires=timedelta(hours=1))
    
    async with db.acquire() as conn:
        await conn.execute("""
            INSERT INTO geo_export (export_id, jurisdiction_id, bbox, format, object_key, expires_at)
            VALUES ($1, $2, ST_MakeEnvelope($3, $4, $5, $6, 4326), $7, $8, NOW() + INTERVAL '1 hour')
        """, export_id, jurisdiction_id, min_lon, min_lat, max_lon, max_lat, payload.format, object_key)
        
    return JSONResponse(status_code=202, content=success_response({
        "exportId": export_id,
        "downloadUrl": url,
        "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    }, correlation_id))
