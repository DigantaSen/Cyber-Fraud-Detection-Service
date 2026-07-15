"""Shared httpx.AsyncClient for Bot → Orchestrator calls."""
from fastapi import Request
import httpx


async def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client
