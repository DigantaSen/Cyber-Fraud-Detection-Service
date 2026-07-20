import httpx
from fastapi import Request
from config import settings

_audit_client = httpx.AsyncClient(base_url=settings.AUDIT_SERVICE_URL, timeout=10.0)
_reporting_client = httpx.AsyncClient(base_url=settings.REPORTING_SERVICE_URL, timeout=30.0)
_notification_client = httpx.AsyncClient(base_url=settings.NOTIFICATION_SERVICE_URL, timeout=10.0)

async def get_audit_client() -> httpx.AsyncClient:
    return _audit_client

async def get_reporting_client() -> httpx.AsyncClient:
    return _reporting_client

async def get_notification_client() -> httpx.AsyncClient:
    return _notification_client

async def close_clients():
    await _audit_client.aclose()
    await _reporting_client.aclose()
    await _notification_client.aclose()
