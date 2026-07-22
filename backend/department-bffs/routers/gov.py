from fastapi.responses import Response
from fastapi import APIRouter, Depends, Request, HTTPException
import httpx
from sse_starlette.sse import EventSourceResponse
import os
from auth import get_current_user

router = APIRouter(prefix="/api/v1/gov")

NOTIFY_URL = os.environ.get("NOTIFY_URL", "http://notification:8000/api/v1/notify")
REPORTING_URL = os.environ.get("REPORTING_URL", "http://reporting-service:8000/api/v1/reports")

MHA_MOCK_URL = os.environ.get("MHA_MOCK_URL", "http://mha-webhook-mock:8000")

@router.get("/alerts")
async def get_alerts(
    request: Request,
    cursor: str = None,
    limit: int = 20,
    from_date: str = None,
    to_date: str = None,
    user=Depends(get_current_user("GOV_OFFICIAL"))
):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{MHA_MOCK_URL}/alerts", timeout=4.0)
            if resp.status_code == 200:
                data = resp.json()
                raw_alerts = data.get("alerts", [])
                # Order by receivedAt DESC
                raw_alerts.sort(key=lambda x: x.get("receivedAt", ""), reverse=True)
                items = []
                for a in raw_alerts[:limit]:
                    items.append({
                        "alertId": a.get("mockAlertId"),
                        "caseId": a.get("caseId"),
                        "alertType": a.get("alertType", "FRAUD_RING_DETECTED"),
                        "riskTier": a.get("riskTier", "HIGH"),
                        "summary": a.get("summary", "MHA Alert Triggered"),
                        "jurisdictionId": a.get("jurisdictionId", "MHA_HQ"),
                        "suspects": a.get("suspects", []),
                        "dispatchedAt": a.get("receivedAt")
                    })
                return {"items": items, "nextCursor": None, "hasMore": False, "total": len(items)}
    except Exception as e:
        pass
    return {"items": [], "nextCursor": None, "hasMore": False, "total": 0}


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
            
            response = await client.get("http://reporting-service:8000/reports", params=params, headers=headers, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])
            for item in items:
                if item.get("packageId"):
                    item["downloadUrl"] = f"/api/v1/gov/reports/packages/{item['packageId']}/download"
            return data
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
            
            response = await client.post("http://reporting-service:8000/reports/intelligence-package", json=body, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            if data.get("packageId"):
                data["downloadUrl"] = f"/api/v1/gov/reports/packages/{data['packageId']}/download"
            return data
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Reporting HTTP Error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BFF Exception {type(e).__name__}: {str(e)}")


@router.get("/reports/packages/{package_id}/download")
async def download_intel_package(
    package_id: str,
    user=Depends(get_current_user("GOV_OFFICIAL"))
):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://reporting-service:8000/reports/packages/{package_id}/download",
                timeout=15.0
            )
            if resp.status_code == 200:
                return Response(
                    content=resp.content,
                    media_type="application/json",
                    headers={
                        "Content-Disposition": resp.headers.get(
                            "Content-Disposition",
                            f'attachment; filename="intelligence_package_{package_id}.json"'
                        )
                    }
                )
            raise HTTPException(status_code=resp.status_code, detail="Package file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")


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
