"""HTTP client for Bot Service downstream calls."""
import httpx
from fastapi import Request


async def get_bot_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.bot_client
