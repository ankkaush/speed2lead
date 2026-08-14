from typing import Optional

import httpx

from app.config import settings

_client: Optional[httpx.AsyncClient] = None


async def init_http_client() -> httpx.AsyncClient:
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
            write=settings.http_read_timeout_seconds,
            pool=settings.http_connect_timeout_seconds,
        )
    )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_http_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client not initialized — init_http_client() must run at app startup")
    return _client
