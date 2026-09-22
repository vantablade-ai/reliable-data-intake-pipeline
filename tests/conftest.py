from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.main import create_app


class LocalClient:
    """Synchronous wrapper around an in-process ASGI transport."""

    def __init__(self, app):
        self.transport = httpx.ASGITransport(app=app)

    def request(self, method: str, url: str, **kwargs: Any):
        async def send():
            async with httpx.AsyncClient(transport=self.transport, base_url="http://testserver") as client:
                return await client.request(method, url, **kwargs)
        return asyncio.run(send())

    def get(self, url: str, **kwargs: Any):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any):
        return self.request("POST", url, **kwargs)


@pytest.fixture()
def app(tmp_path: Path):
    application = create_app(tmp_path / "test.db")
    yield application
    application.state.connection.close()


@pytest.fixture()
def client(app):
    return LocalClient(app)
