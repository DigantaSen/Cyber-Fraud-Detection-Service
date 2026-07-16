"""HTTP client for Evidence Service downstream calls."""
import httpx
from fastapi import Request


async def get_evidence_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.evidence_client
