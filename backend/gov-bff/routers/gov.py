import json
import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
import httpx
import asyncio

from clients.clients import get_audit_client, get_reporting_client, get_notification_client
from security.jwt import require_role

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Gov BFF"])


def _corr(request: Request) -> str:
    return request.headers.get("X-Correlation-ID", "")


def _forward_headers(request: Request, current_user: dict) -> dict:
    ctx = {
        "userId": current_user.get("sub", "unknown"),
        "role": current_user.get("role", "GOV_OFFICIAL"),
        "jurisdictionId": current_user.get("jurisdictionId", "MHA_HQ")
    }
    return {
        "X-Correlation-ID": _corr(request),
        "X-User-Context": json.dumps(ctx)
    }


async def _proxy(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict:
    try:
        response = await client.request(method, path, **kwargs)
        if response.status_code in (200, 201, 202):
            return response.json()
        if 400 <= response.status_code < 500:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        raise HTTPException(status_code=502, detail={"errorCode": "UPSTREAM_ERROR", "message": f"Upstream error {response.status_code}"})
    except httpx.RequestError as e:
        logger.error(f"Downstream error: {e}")
        raise HTTPException(status_code=503, detail={"errorCode": "SERVICE_UNAVAILABLE", "message": "Downstream service unavailable"})


async def _proxy_raw(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    try:
        response = await client.request(method, path, **kwargs)
        if 400 <= response.status_code < 500:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        if response.status_code >= 500:
            raise HTTPException(status_code=502, detail={"errorCode": "UPSTREAM_ERROR", "message": f"Upstream error {response.status_code}"})
        return Response(content=response.content, status_code=response.status_code, headers=dict(response.headers))
    except httpx.RequestError as e:
        logger.error(f"Downstream error: {e}")
        raise HTTPException(status_code=503, detail={"errorCode": "SERVICE_UNAVAILABLE", "message": "Downstream service unavailable"})


@router.get("/alerts")
async def get_alerts(
    request: Request,
    current_user=Depends(require_role("GOV_OFFICIAL", "ADMIN")),
    audit_client: httpx.AsyncClient = Depends(get_audit_client)
):
    """Get high-priority MHA alerts stream."""
    query_params = request.query_params
    headers = _forward_headers(request, current_user)
    
    # Actually calls Audit service: GET /api/v1/audit/events?eventType=MHAAlert.Sent
    # Need to pass down the params
    params = dict(query_params)
    params["eventType"] = "MHAAlert.Sent"
    
    result = await _proxy(audit_client, "GET", "/api/v1/audit/events", params=params, headers=headers)
    
    # Audit returns generic events, we need to map them back to the Gov BFF alert format
    items = []
    for ev in result.get("items", []):
        d = ev.get("data", {})
        items.append({
            "alertId": ev.get("eventId"),
            "alertType": d.get("alertType"),
            "riskTier": "CRITICAL",
            "summary": d.get("summary", "MHA Alert Triggered"),
            "jurisdictionId": d.get("jurisdictionId"),
            "suspects": d.get("suspects", []),
            "dispatchedAt": ev.get("timestamp")
        })
        
    return {
        "items": items,
        "nextCursor": result.get("nextCursor"),
        "hasMore": result.get("hasMore", False),
        "total": result.get("total", len(items))
    }


@router.get("/reports")
async def get_reports(
    request: Request,
    current_user=Depends(require_role("GOV_OFFICIAL", "ADMIN")),
    reporting_client: httpx.AsyncClient = Depends(get_reporting_client)
):
    """List available NCRB reports and intelligence packages."""
    headers = _forward_headers(request, current_user)
    return await _proxy(reporting_client, "GET", "/api/v1/reports", params=request.query_params, headers=headers)


@router.post("/reports/intelligence-package")
async def request_intelligence_package(
    request: Request,
    current_user=Depends(require_role("GOV_OFFICIAL", "ADMIN")),
    reporting_client: httpx.AsyncClient = Depends(get_reporting_client)
):
    """Request a new intelligence package for a case."""
    headers = _forward_headers(request, current_user)
    body = await request.body()
    headers["Content-Type"] = request.headers.get("Content-Type", "application/json")
    return await _proxy(reporting_client, "POST", "/api/v1/reports/intelligence-package", content=body, headers=headers)


@router.get("/stream")
async def sse_stream(
    request: Request,
    current_user=Depends(require_role("GOV_OFFICIAL", "ADMIN")),
    notification_client: httpx.AsyncClient = Depends(get_notification_client)
):
    """SSE stream for real-time national-level alerts."""
    headers = _forward_headers(request, current_user)
    return await _proxy_raw(notification_client, "GET", "/api/v1/notify/stream", headers=headers)
