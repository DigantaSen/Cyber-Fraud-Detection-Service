"""Shared httpx.AsyncClient dependency for Case Service."""
from fastapi import Request
import httpx


async def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the shared AsyncClient initialized in lifespan."""
    return request.app.state.http_client
