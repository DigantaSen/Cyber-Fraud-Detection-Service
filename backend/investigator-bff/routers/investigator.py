import uuid
from typing import Optional
import asyncio

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from clients.clients import (
    get_case_client,
    get_search_client,
    get_geo_client,
    get_graph_client,
    get_evidence_client,
    get_reporting_client,
    get_notification_client,
)
from response_helpers import success_response, error_response
from security.jwt import require_role

router = APIRouter(prefix="/investigator", tags=["Investigator"])

def _corr(request: Request) -> str:
    return request.headers.get("X-Correlation-ID", str(uuid.uuid4()))

def _forward_headers(request: Request, current_user) -> dict:
    headers = {"X-Correlation-ID": _corr(request)}
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    if current_user:
        import json
        headers["X-User-Context"] = json.dumps({
            "userId": str(current_user.user_id) if current_user.user_id else None,
            "role": current_user.role,
            "jti": getattr(current_user, "jti", None),
            "jurisdictionId": current_user.jurisdiction_id
        })
    return headers

async def _proxy(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict:
    try:
        response = await client.request(method, path, **kwargs)
        if response.status_code in (200, 201):
            return response.json()
        if 400 <= response.status_code < 500:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        raise HTTPException(status_code=502, detail={"errorCode": "UPSTREAM_ERROR", "message": "Upstream service error"})
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail={"errorCode": "SERVICE_UNAVAILABLE", "message": "Downstream service unavailable"})

async def _proxy_raw(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    try:
        response = await client.request(method, path, **kwargs)
        if 400 <= response.status_code < 500:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        if response.status_code >= 500:
            raise HTTPException(status_code=502, detail={"errorCode": "UPSTREAM_ERROR", "message": "Upstream service error"})
        from fastapi.responses import Response
        return Response(content=response.content, status_code=response.status_code, headers=dict(response.headers))
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail={"errorCode": "SERVICE_UNAVAILABLE", "message": "Downstream service unavailable"})


@router.get("/cases")
async def get_cases(
    request: Request,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    search_client: httpx.AsyncClient = Depends(get_search_client),
):
    """Live case queue — SSE-enhanced paginated list."""
    query_params = request.query_params
    result = await _proxy(
        search_client, "GET", "/api/v1/search/cases", params=query_params, headers=_forward_headers(request, current_user)
    )
    return result

@router.get("/cases/{case_id}")
async def get_case_detail(
    request: Request,
    case_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    case_client: httpx.AsyncClient = Depends(get_case_client),
    graph_client: httpx.AsyncClient = Depends(get_graph_client),
    geo_client: httpx.AsyncClient = Depends(get_geo_client),
    evidence_client: httpx.AsyncClient = Depends(get_evidence_client),
):
    """Full case detail — parallel aggregation."""
    headers = _forward_headers(request, current_user)
    
    case_result = await _proxy(case_client, "GET", f"/api/v1/cases/{case_id}", headers=headers)
    case_data = case_result.get("data", {})
    
    suspect_phone = case_data.get("suspectPhone", "")
    # complaintLat/Lon may be serialized as Decimal strings — always cast to float
    _lat = case_data.get("complaintLat")
    _lon = case_data.get("complaintLon")
    complaint_lat = float(_lat) if _lat is not None else None
    complaint_lon = float(_lon) if _lon is not None else None
    
    graph_coro = None
    anchor_id = suspect_phone or case_id
    if anchor_id:
        graph_coro = _proxy(graph_client, "GET", "/api/v1/graph/linkages", params={"entityId": anchor_id, "hops": 2}, headers=headers)
        
    geo_coro = None
    if complaint_lat is not None and complaint_lon is not None:
        bbox = f"{complaint_lon-0.05},{complaint_lat-0.05},{complaint_lon+0.05},{complaint_lat+0.05}"
        geo_coro = _proxy(geo_client, "GET", "/api/v1/geo/hotspots", params={"bbox": bbox}, headers=headers)
        
    # Evidence: use correct path and catch failures so they don't break the whole route
    async def _fetch_evidence():
        try:
            r = await evidence_client.get(f"/cases/{case_id}/evidence", headers=headers)
            if r.status_code == 200:
                raw = r.json()
                # Evidence service returns plain list []
                return raw if isinstance(raw, list) else raw.get("data", [])
        except Exception:
            pass
        return []

    evidence_coro = _fetch_evidence()

    coros = [evidence_coro]
    if graph_coro:
        coros.append(graph_coro)
    if geo_coro:
        coros.append(geo_coro)

    results = await asyncio.gather(*coros, return_exceptions=True)

    evidence_list = results[0] if isinstance(results[0], list) else []
    
    idx = 1
    graph_data = {}
    if graph_coro:
        graph_data = results[idx].get("data", {}) if not isinstance(results[idx], Exception) and isinstance(results[idx], dict) else {}
        idx += 1
        
    nearby_hotspots = []
    if geo_coro:
        nearby_hotspots = results[idx].get("data", []) if not isinstance(results[idx], Exception) and isinstance(results[idx], dict) else []

    return success_response({
        "case": case_data,
        "prediction": case_data.get("prediction", {}),
        "graphSummary": graph_data,
        "nearbyHotspots": nearby_hotspots,
        "evidence": evidence_list,
        "timeline": case_data.get("timeline", [])
    }, _corr(request))

@router.patch("/cases/{case_id}/state")
@router.post("/cases/{case_id}/state")
async def update_case_state(
    request: Request,
    case_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    case_client: httpx.AsyncClient = Depends(get_case_client),
):
    headers = _forward_headers(request, current_user)
    body = await request.body()
    headers["Content-Type"] = request.headers.get("Content-Type", "application/json")
    return await _proxy(case_client, "PATCH", f"/api/v1/cases/{case_id}/state", content=body, headers=headers)

@router.post("/cases/{case_id}/override")
async def override_verdict(
    request: Request,
    case_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    case_client: httpx.AsyncClient = Depends(get_case_client),
):
    headers = _forward_headers(request, current_user)
    body = await request.body()
    content_type = request.headers.get("Content-Type", "application/json")
    headers["Content-Type"] = content_type
    return await _proxy(case_client, "PATCH", f"/api/v1/cases/{case_id}/verdict/override", content=body, headers=headers)

@router.get("/cases/{case_id}/geo")
async def get_case_geo(
    request: Request,
    case_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    case_client: httpx.AsyncClient = Depends(get_case_client),
    geo_client: httpx.AsyncClient = Depends(get_geo_client),
):
    headers = _forward_headers(request, current_user)
    case_result = await _proxy(case_client, "GET", f"/api/v1/cases/{case_id}", headers=headers)
    case_data = case_result.get("data", {})
    complaint_lat = case_data.get("complaintLat")
    complaint_lon = case_data.get("complaintLon")
    if complaint_lat is not None and complaint_lon is not None:
        bbox = f"{complaint_lon-0.05},{complaint_lat-0.05},{complaint_lon+0.05},{complaint_lat+0.05}"
        return await _proxy(geo_client, "GET", "/api/v1/geo/hotspots", params={"bbox": bbox}, headers=headers)
    return success_response([], _corr(request))

@router.get("/cases/{case_id}/graph")
async def get_case_graph(
    request: Request,
    case_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    case_client: httpx.AsyncClient = Depends(get_case_client),
    graph_client: httpx.AsyncClient = Depends(get_graph_client),
):
    headers = _forward_headers(request, current_user)
    case_result = await _proxy(case_client, "GET", f"/api/v1/cases/{case_id}", headers=headers)
    raw_data = case_result.get("data", {})
    case_data = raw_data.get("case", raw_data) if isinstance(raw_data, dict) else {}
    entity_id = case_data.get("suspectPhone") or case_data.get("suspect_phone") or case_data.get("suspectAccount") or case_data.get("suspect_account") or case_id
    return await _proxy(graph_client, "GET", "/api/v1/graph/linkages", params={"entityId": entity_id, "hops": 2}, headers=headers)

@router.post("/cases/{case_id}/evidence")
async def upload_evidence(
    request: Request,
    case_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    evidence_client: httpx.AsyncClient = Depends(get_evidence_client),
):
    headers = _forward_headers(request, current_user)
    body = await request.body()
    content_type = request.headers.get("Content-Type", "application/json")
    headers["Content-Type"] = content_type
    return await _proxy(evidence_client, "POST", f"/cases/{case_id}/evidence", content=body, headers=headers)

@router.post("/reports/intelligence-package")
async def generate_intelligence_package(
    request: Request,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    reporting_client: httpx.AsyncClient = Depends(get_reporting_client),
):
    headers = _forward_headers(request, current_user)
    body = await request.body()
    content_type = request.headers.get("Content-Type", "application/json")
    headers["Content-Type"] = content_type
    return await _proxy(reporting_client, "POST", "/reports/intelligence-package", content=body, headers=headers)

@router.get("/stream")
async def stream_events(
    request: Request,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    notification_client: httpx.AsyncClient = Depends(get_notification_client),
):
    headers = _forward_headers(request, current_user)
    return await _proxy_raw(notification_client, "GET", "/api/v1/notify/stream", headers=headers)


@router.patch("/cases/{case_id}/state")
async def update_case_state(
    request: Request,
    case_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    case_client: httpx.AsyncClient = Depends(get_case_client),
):
    headers = _forward_headers(request, current_user)
    body = await request.body()
    content_type = request.headers.get("Content-Type", "application/json")
    headers["Content-Type"] = content_type
    return await _proxy(case_client, "PATCH", f"/api/v1/cases/{case_id}/state", content=body, headers=headers)


@router.get("/graph/global")
async def get_global_syndicate_graph(
    request: Request,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    graph_client: httpx.AsyncClient = Depends(get_graph_client),
):
    headers = _forward_headers(request, current_user)
    return await _proxy(graph_client, "GET", "/api/v1/graph/global", headers=headers)


@router.get("/cases/{case_id}/evidence")
async def get_case_evidence_list(
    request: Request,
    case_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    evidence_client: httpx.AsyncClient = Depends(get_evidence_client),
):
    headers = _forward_headers(request, current_user)
    result = await _proxy(evidence_client, "GET", f"/cases/{case_id}/evidence", headers=headers)
    if isinstance(result, list):
        return success_response(result, _corr(request))
    return result

@router.get("/evidence/{evidence_id}")
async def get_evidence_download(
    request: Request,
    evidence_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    evidence_client: httpx.AsyncClient = Depends(get_evidence_client),
):
    headers = _forward_headers(request, current_user)
    return await _proxy(evidence_client, "GET", f"/evidence/{evidence_id}", headers=headers)

@router.post("/evidence/{evidence_id}/confirm")
async def confirm_investigator_evidence(
    request: Request,
    evidence_id: str,
    current_user=Depends(require_role("INVESTIGATOR", "ADMIN")),
    evidence_client: httpx.AsyncClient = Depends(get_evidence_client),
):
    headers = _forward_headers(request, current_user)
    body = await request.body()
    content_type = request.headers.get("Content-Type", "application/json")
    headers["Content-Type"] = content_type
    return await _proxy(evidence_client, "POST", f"/evidence/{evidence_id}/confirm", content=body, headers=headers)
