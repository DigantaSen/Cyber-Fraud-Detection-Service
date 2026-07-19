"""HTTP client for Case Service downstream calls."""
import httpx
from fastapi import Request


async def get_case_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.case_client
