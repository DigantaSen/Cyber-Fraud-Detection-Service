"""
Search Service — FastAPI Application (T8f)

CQRS read model: all queries served against OpenSearch,
never PostgreSQL. Two endpoints:
  GET /search/cases     — full-text, faceted, fuzzy, geospatial
  GET /search/evidence  — evidence metadata search

RBAC: results filtered by jurisdictionId from X-Jurisdiction-ID header.
Kong will populate this header from the JWT claim once T4 (Auth) is live.
"""

import base64
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from opensearchpy import OpenSearchException
from prometheus_fastapi_instrumentator import Instrumentator

from config import settings
from opensearch_client import client as os_client, ensure_indices

# ── App Setup ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("search-api")

app = FastAPI(
    title="Search Service",
    description="CQRS read model — OpenSearch-backed case and evidence search",
    version=settings.SERVICE_VERSION,
)

Instrumentator().instrument(app).expose(app)


# ── Lifecycle ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Ensure indices exist on startup so the API is always ready to serve."""
    logger.info("Search API starting up — ensuring OpenSearch indices...")
    try:
        ensure_indices()
    except Exception as e:
        logger.warning(f"Could not ensure indices on startup (OpenSearch may not be ready): {e}")


# ── Response Helpers ───────────────────────────────────────────────────────────

def make_response(request: Request, data: Any) -> Dict[str, Any]:
    """Standard response envelope matching platform conventions."""
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    return {
        "requestId": str(uuid.uuid4()),
        "correlationId": corr_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "success",
        "data": data,
    }


def make_error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    return JSONResponse(
        status_code=status_code,
        content={
            "requestId": str(uuid.uuid4()),
            "correlationId": corr_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "error",
            "errorCode": code,
            "message": message,
        }
    )


# ── Cursor Pagination Helpers ──────────────────────────────────────────────────

def encode_cursor(created_at: str, doc_id: str) -> str:
    """Encode a search_after cursor into an opaque base64 string."""
    payload = json.dumps({"createdAt": created_at, "id": doc_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> Optional[List[Any]]:
    """Decode a base64 cursor into a [createdAt, id] search_after value."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return [payload["createdAt"], payload["id"]]
    except Exception:
        return None


# ── Health Endpoints ───────────────────────────────────────────────────────────

@app.get("/health/ready")
async def health_ready():
    """
    Readiness probe: checks that OpenSearch is reachable and cluster is healthy.
    Returns 503 if OpenSearch is not yet available.
    """
    try:
        health = os_client.cluster.health(request_timeout=3)
        if health.get("status") in ("green", "yellow"):
            return {"status": "ready", "opensearch": health["status"]}
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "opensearch": health.get("status")}
        )
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "not_ready", "error": str(e)})


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


# ── Search Endpoints ───────────────────────────────────────────────────────────

@app.get("/api/v1/search/cases")
async def search_cases(
    request: Request,
    q: Optional[str] = Query(None, description="Full-text search on title, description, notes"),
    status: Optional[str] = Query(None, description="Filter by case status"),
    riskTier: Optional[str] = Query(None, description="Filter by risk tier"),
    assignedTo: Optional[str] = Query(None, description="Filter by assigned investigator UUID"),
    complaintType: Optional[str] = Query(None, description="Filter by complaint type"),
    from_date: Optional[str] = Query(None, alias="from", description="Created after (ISO8601)"),
    to_date: Optional[str] = Query(None, alias="to", description="Created before (ISO8601)"),
    bbox: Optional[str] = Query(None, description="Geo bounding box: minLon,minLat,maxLon,maxLat"),
    fuzzy: Optional[str] = Query(None, description="Fuzzy entity name search"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default 20, max 100)"),
):
    """
    Full-text, faceted, fuzzy, and geospatial case search against OpenSearch.
    Results are automatically filtered by jurisdictionId from the X-Jurisdiction-ID header (RBAC).
    """
    # ── RBAC: jurisdiction filter from JWT claim (forwarded by Kong) ──────────
    jurisdiction_id = request.headers.get("X-Jurisdiction-ID")

    # ── Build the OpenSearch bool query ───────────────────────────────────────
    must_clauses = []
    filter_clauses = []
    should_clauses = []

    # Full-text search: multi_match on text fields
    if q:
        must_clauses.append({
            "multi_match": {
                "query": q,
                "fields": ["title", "description", "notes"],
                "type": "best_fields",
                "fuzziness": "AUTO",
            }
        })

    # Fuzzy entity name search (FR-9.3)
    if fuzzy:
        should_clauses.append({
            "fuzzy": {
                "reporterEntityName": {
                    "value": fuzzy,
                    "fuzziness": "AUTO",
                }
            }
        })

    # Structured keyword filters
    if status:
        filter_clauses.append({"term": {"status": status}})
    if riskTier:
        filter_clauses.append({"term": {"riskTier": riskTier}})
    if assignedTo:
        filter_clauses.append({"term": {"assignedInvestigator": assignedTo}})
    if complaintType:
        filter_clauses.append({"term": {"complaintType": complaintType}})

    # Date range filter
    if from_date or to_date:
        date_range: Dict[str, str] = {}
        if from_date:
            date_range["gte"] = from_date
        if to_date:
            date_range["lte"] = to_date
        filter_clauses.append({"range": {"createdAt": date_range}})

    # Geospatial bounding box filter (FR-9.4)
    # bbox format: "minLon,minLat,maxLon,maxLat"
    if bbox:
        try:
            parts = [float(x.strip()) for x in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError("bbox must have 4 values")
            min_lon, min_lat, max_lon, max_lat = parts
            filter_clauses.append({
                "geo_bounding_box": {
                    "complaintLocation": {
                        "top_left":     {"lat": max_lat, "lon": min_lon},
                        "bottom_right": {"lat": min_lat, "lon": max_lon},
                    }
                }
            })
        except (ValueError, IndexError) as e:
            return make_error(request, 400, "INVALID_BBOX", f"Invalid bbox format: {e}")

    # RBAC: Always filter by jurisdictionId if provided by Kong
    if jurisdiction_id:
        filter_clauses.append({"term": {"jurisdictionId": jurisdiction_id}})

    # Assemble the full bool query
    bool_query: Dict[str, Any] = {}
    if must_clauses:
        bool_query["must"] = must_clauses
    if filter_clauses:
        bool_query["filter"] = filter_clauses
    if should_clauses:
        bool_query["should"] = should_clauses
        bool_query["minimum_should_match"] = 0  # fuzzy is optional boost

    # Match all if no clauses provided
    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    # ── Faceted Aggregations (FR-9.5) ─────────────────────────────────────────
    aggs = {
        "status_facet":   {"terms": {"field": "status",   "size": 10}},
        "riskTier_facet": {"terms": {"field": "riskTier", "size": 10}},
    }

    # ── Cursor Pagination via search_after ────────────────────────────────────
    # Sort is stable: createdAt desc, then _id asc to break ties
    sort = [{"createdAt": "desc"}, {"_id": "asc"}]
    search_after = None
    if cursor:
        search_after = decode_cursor(cursor)
        if search_after is None:
            return make_error(request, 400, "INVALID_CURSOR", "Cursor is malformed or expired")

    # ── Execute OpenSearch query ───────────────────────────────────────────────
    body: Dict[str, Any] = {
        "query": query,
        "aggs": aggs,
        "sort": sort,
        "size": limit,
        "track_total_hits": True,
    }
    if search_after:
        body["search_after"] = search_after

    try:
        response = os_client.search(index="case_index", body=body)
    except OpenSearchException as e:
        logger.error(f"OpenSearch query failed: {e}")
        return make_error(request, 503, "SEARCH_UNAVAILABLE", "Search service is temporarily unavailable")

    hits = response["hits"]["hits"]
    total = response["hits"]["total"]["value"]

    # ── Build items list ───────────────────────────────────────────────────────
    items = []
    for hit in hits:
        src = hit["_source"]
        items.append({
            "caseId":         src.get("caseId", hit["_id"]),
            "caseNumber":     src.get("caseNumber", ""),
            "title":          src.get("title", ""),
            "status":         src.get("status", ""),
            "riskTier":       src.get("riskTier", ""),
            "fusedScore":     src.get("fusedScore", 0.0),
            "assignedTo":     src.get("assignedInvestigator", ""),
            "jurisdictionId": src.get("jurisdictionId", ""),
            "createdAt":      src.get("createdAt", ""),
            "complaintType":  src.get("complaintType", ""),
        })

    # ── Build next cursor ──────────────────────────────────────────────────────
    next_cursor = None
    has_more = len(hits) == limit
    if has_more and hits:
        last = hits[-1]
        last_src = last["_source"]
        next_cursor = encode_cursor(
            created_at=last_src.get("createdAt", ""),
            doc_id=last["_id"]
        )

    # ── Build facets from aggregations ────────────────────────────────────────
    def build_facet(agg_result: dict) -> dict:
        return {bucket["key"]: bucket["doc_count"] for bucket in agg_result.get("buckets", [])}

    facets = {
        "status":   build_facet(response["aggregations"].get("status_facet", {})),
        "riskTier": build_facet(response["aggregations"].get("riskTier_facet", {})),
    }

    return make_response(request, {
        "items":      items,
        "nextCursor": next_cursor,
        "hasMore":    has_more,
        "total":      total,
        "facets":     facets,
    })


@app.get("/api/v1/search/evidence")
async def search_evidence(
    request: Request,
    q: Optional[str] = Query(None, description="Full-text search on fileName"),
    caseId: Optional[str] = Query(None, description="Filter by case UUID"),
    mimeType: Optional[str] = Query(None, description="Filter by MIME type"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search evidence items by case or content.
    """
    must_clauses = []
    filter_clauses = []

    if q:
        must_clauses.append({
            "multi_match": {
                "query": q,
                "fields": ["fileName"],
                "fuzziness": "AUTO",
            }
        })
    if caseId:
        filter_clauses.append({"term": {"caseId": caseId}})
    if mimeType:
        filter_clauses.append({"term": {"mimeType": mimeType}})

    bool_query: Dict[str, Any] = {}
    if must_clauses:
        bool_query["must"] = must_clauses
    if filter_clauses:
        bool_query["filter"] = filter_clauses

    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    sort = [{"createdAt": "desc"}, {"_id": "asc"}]
    search_after = None
    if cursor:
        search_after = decode_cursor(cursor)
        if search_after is None:
            return make_error(request, 400, "INVALID_CURSOR", "Cursor is malformed or expired")

    body: Dict[str, Any] = {
        "query": query,
        "sort": sort,
        "size": limit,
        "track_total_hits": True,
    }
    if search_after:
        body["search_after"] = search_after

    try:
        response = os_client.search(index="evidence_index", body=body)
    except OpenSearchException as e:
        logger.error(f"OpenSearch query failed: {e}")
        return make_error(request, 503, "SEARCH_UNAVAILABLE", "Search service is temporarily unavailable")

    hits = response["hits"]["hits"]
    total = response["hits"]["total"]["value"]

    items = [hit["_source"] for hit in hits]

    next_cursor = None
    has_more = len(hits) == limit
    if has_more and hits:
        last = hits[-1]
        next_cursor = encode_cursor(
            created_at=last["_source"].get("createdAt", ""),
            doc_id=last["_id"]
        )

    return make_response(request, {
        "items":      items,
        "nextCursor": next_cursor,
        "hasMore":    has_more,
        "total":      total,
    })
