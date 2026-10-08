"""A tiny fake Telegram Bot API server for local development and demos.

Run it, then point flowpilot at it::

    python scripts/mock_telegram.py --port 8081 &
    TELEGRAM_API_BASE=http://127.0.0.1:8081 TELEGRAM_BOT_TOKEN=test TELEGRAM_CHAT_ID=1 \\
        flowpilot -p examples run crypto-digest

Every received message is printed to stdout and kept in memory
(``GET /messages`` returns them as JSON).
"""

from __future__ import annotations

import argparse
import itertools
from typing import Any

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI(title="mock telegram")
messages: list[dict[str, Any]] = []
counter = itertools.count(1)


@app.post("/bot{token}/{method}")
async def bot_method(token: str, method: str, request: Request) -> dict[str, Any]:
    ctype = request.headers.get("content-type", "")
    if "multipart" in ctype:
        form = await request.form()
        data: dict[str, Any] = {
            k: (v if isinstance(v, str) else f"<file {v.filename}>") for k, v in form.items()
        }
    else:
        data = await request.json()
    entry = {"method": method, **data}
    messages.append(entry)
    preview = str(data.get("text") or data.get("caption") or "")[:120].replace("\n", " ")
    print(f"[mock-telegram] {method} → {data.get('chat_id')}: {preview}", flush=True)
    return {
        "ok": True,
        "result": {"message_id": next(counter), "chat": {"id": data.get("chat_id")}},
    }


@app.get("/messages")
async def list_messages() -> list[dict[str, Any]]:
    return messages


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
