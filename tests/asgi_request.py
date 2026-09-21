from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app


async def send(db_path: Path, request: dict) -> dict:
    app = create_app(db_path)
    transport = httpx.ASGITransport(app=app)
    kwargs = request.get("kwargs", {})
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.request(request["method"], request["url"], **kwargs)
    return {"status_code": response.status_code, "text": response.text}


if __name__ == "__main__":
    request = json.load(sys.stdin)

    async def main() -> dict:
        return await asyncio.wait_for(send(Path(sys.argv[1]), request), timeout=5)

    print(json.dumps(asyncio.run(main())))
