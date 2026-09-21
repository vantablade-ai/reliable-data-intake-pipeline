from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest


class LocalClient:
    """Synchronous test client that exercises the ASGI app in a child process."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def request(self, method: str, url: str, **kwargs: Any) -> "LocalResponse":
        request = {"method": method, "url": url, "kwargs": kwargs}
        helper = Path(__file__).with_name("asgi_request.py")
        completed = subprocess.run(
            [sys.executable, str(helper), str(self.db_path)],
            input=json.dumps(request), text=True, capture_output=True, check=True, timeout=10,
            cwd=Path(__file__).parents[1],
        )
        return LocalResponse(json.loads(completed.stdout))

    def get(self, url: str, **kwargs: Any) -> "LocalResponse":
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> "LocalResponse":
        return self.request("POST", url, **kwargs)


class LocalResponse:
    def __init__(self, payload: dict[str, Any]):
        self.status_code = payload["status_code"]
        self.text = payload["text"]

    def json(self) -> Any:
        return json.loads(self.text)


@pytest.fixture()
def client(tmp_path: Path) -> LocalClient:
    return LocalClient(tmp_path / "test.db")
