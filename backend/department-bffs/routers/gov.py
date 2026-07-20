from fastapi import APIRouter, Depends, Request, HTTPException
import httpx
from sse_starlette.sse import EventSourceResponse
import os
from auth import get_current_user

router = APIRouter(prefix="/api/v1/gov")

NOTIFY_URL = os.environ.get("NOTIFY_URL", "http://notification:8000/api/v1/notify")
REPORTING_URL = os.environ.get("REPORTING_URL", "http://reporting:8000/api/v1/reports")

@router.get("/alerts")
async def get_alerts(
    request: Request,
    cursor: str = None,
    limit: int = 20,
    from_date: str = None,
    to_date: str = None,
    user=Depends(get_current_user("GOV_OFFICIAL"))
):
    # Proxy to Notification Service audit log for MHAAlert.Sent events
    # We will use httpx to proxy the request.
    try:
        async with httpx.AsyncClient() as client:
            params = {"cursor": cursor, "limit": limit, "from": from_date, "to": to_date}
            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}
            
            headers = {"X-User-Role": "GOV_OFFICIAL"}
            if "jurisdictionId" in user:
                headers["X-Jurisdiction-Id"] = user["jurisdictionId"]
            
            # Note: actual endpoint on notification might differ, using a likely one.
            response = await client.get(f"{NOTIFY_URL}/alerts", params=params, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError:
        # Defensive fallback if Notification service is down
        return {"items": [], "nextCursor": None, "hasMore": False, "total": 0}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


@router.get("/reports")
async def get_reports(
    request: Request,
    cursor: str = None,
    limit: int = 20,
    user=Depends(get_current_user("GOV_OFFICIAL"))
):
    try:
        async with httpx.AsyncClient() as client:
            params = {"cursor": cursor, "limit": limit}
            params = {k: v for k, v in params.items() if v is not None}
            
            headers = {"X-User-Role": "GOV_OFFICIAL"}
            if "jurisdictionId" in user:
                headers["X-Jurisdiction-Id"] = user["jurisdictionId"]
            
            response = await client.get(f"{REPORTING_URL}", params=params, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError:
        # Defensive fallback if Reporting service is down
        return {"items": [], "nextCursor": None, "hasMore": False, "total": 0}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


@router.post("/reports/intelligence-package")
async def request_intelligence_package(
    request: Request,
    user=Depends(get_current_user("GOV_OFFICIAL"))
):
    body = await request.json()
    try:
        async with httpx.AsyncClient() as client:
            headers = {"X-User-Role": "GOV_OFFICIAL"}
            if "jurisdictionId" in user:
                headers["X-Jurisdiction-Id"] = user["jurisdictionId"]
            
            response = await client.post(f"{REPORTING_URL}/intelligence-package", json=body, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError:
        # Defensive fallback
        raise HTTPException(status_code=503, detail="Reporting service unavailable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


@router.get("/stream")
async def stream_gov_events(request: Request, user=Depends(get_current_user("GOV_OFFICIAL"))):
    # Proxy to Notification Service SSE
    async def sse_generator():
        try:
            async with httpx.AsyncClient() as client:
                headers = {"X-User-Role": "GOV_OFFICIAL"}
                if "jurisdictionId" in user:
                    headers["X-Jurisdiction-Id"] = user["jurisdictionId"]
                
                async with client.stream("GET", f"{NOTIFY_URL}/stream", headers=headers) as response:
                    async for line in response.aiter_lines():
                        if line:
                            yield line
        except httpx.ConnectError:
            # Defensive fallback
            yield "event: error\ndata: downstream notification service unavailable\n\n"

    return EventSourceResponse(sse_generator())
