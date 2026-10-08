"""``telegram`` — send messages, documents and photos through the Telegram Bot API.

Configuration (env vars, overridable per step):

* ``TELEGRAM_BOT_TOKEN`` — bot token from @BotFather
* ``TELEGRAM_CHAT_ID`` — default chat/channel id (e.g. ``123456`` or ``@my_channel``)
* ``TELEGRAM_API_BASE`` — Bot API base URL (default ``https://api.telegram.org``);
  point it at a self-hosted Bot API server or a reverse proxy if
  ``api.telegram.org`` is not reachable from your server.

Outgoing requests honour ``HTTPS_PROXY`` / ``ALL_PROXY`` (install the
``flowpilot[socks]`` extra for SOCKS proxies).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError, StepError
from flowpilot.registry import step

MAX_MESSAGE = 4096
MAX_CAPTION = 1024


def split_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Split ``text`` into chunks of at most ``limit`` chars, preferring line breaks."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()] or [text[:limit]]


class _Bot:
    def __init__(self, ctx: StepContext, token: str) -> None:
        self.ctx = ctx
        self.token = token
        self.base = f"{ctx.settings.telegram_api_base.rstrip('/')}/bot{token}"

    async def call(
        self, method: str, data: dict[str, Any], files: dict[str, Any] | None = None
    ) -> Any:
        url = f"{self.base}/{method}"
        clean = {k: v for k, v in data.items() if v is not None}
        try:
            if files:
                form = {
                    k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in clean.items()
                }
                resp = await self.ctx.http.post(url, data=form, files=files, timeout=120)
            else:
                resp = await self.ctx.http.post(url, json=clean, timeout=30)
        except httpx.HTTPError as exc:
            message = str(exc).replace(self.token, "<token>")
            raise StepError(f"telegram {method}: {type(exc).__name__}: {message}") from None
        try:
            body = resp.json()
        except ValueError:
            raise StepError(
                f"telegram {method}: HTTP {resp.status_code} (non-JSON response)",
                retryable=resp.status_code >= 500,
            ) from None
        if not body.get("ok"):
            code = body.get("error_code", resp.status_code)
            desc = body.get("description", "unknown error")
            raise StepError(
                f"telegram {method}: {code} {desc}", retryable=code == 429 or code >= 500
            )
        return body.get("result")


def _is_local(ctx: StepContext, ref: str) -> Path | None:
    if ref.startswith(("http://", "https://")):
        return None
    path = ctx.resolve_path(ref)
    return path if path.is_file() else None


@step("telegram")
async def telegram(
    ctx: StepContext,
    text: str | None = None,
    chat_id: str | int | None = None,
    parse_mode: str | None = "HTML",
    document: str | None = None,
    photo: str | None = None,
    caption: str | None = None,
    disable_preview: bool = True,
    silent: bool = False,
    thread_id: int | None = None,
    token: str | None = None,
    method: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a Telegram message, document or photo (or call any Bot API ``method``)."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise StepConfigError("telegram: no bot token (set TELEGRAM_BOT_TOKEN or pass token)")
    bot = _Bot(ctx, str(token))

    if method:
        result = await bot.call(method, dict(payload or {}))
        return {"result": result}

    chat = chat_id if chat_id not in (None, "") else os.environ.get("TELEGRAM_CHAT_ID")
    if not chat:
        raise StepConfigError("telegram: no chat_id (set TELEGRAM_CHAT_ID or pass chat_id)")
    common: dict[str, Any] = {
        "chat_id": chat,
        "disable_notification": silent,
        "message_thread_id": thread_id,
    }
    if parse_mode:
        common["parse_mode"] = parse_mode

    for kind, ref, api_method in (
        ("document", document, "sendDocument"),
        ("photo", photo, "sendPhoto"),
    ):
        if not ref:
            continue
        cap = caption if caption is not None else text
        data = {**common, "caption": cap[:MAX_CAPTION] if cap else None}
        local = _is_local(ctx, ref)
        if local is not None:
            with local.open("rb") as fh:
                result = await bot.call(api_method, data, files={kind: (local.name, fh)})
        else:
            result = await bot.call(api_method, {**data, kind: ref})
        ctx.log.info(f"sent {kind} to {chat}")
        return {"chat_id": chat, "message_ids": [result.get("message_id")]}

    if not text:
        raise StepConfigError("telegram: provide text, document or photo")
    ids: list[Any] = []
    for chunk in split_message(str(text)):
        result = await bot.call(
            "sendMessage",
            {**common, "text": chunk, "link_preview_options": {"is_disabled": disable_preview}},
        )
        ids.append(result.get("message_id"))
    ctx.log.info(f"sent {len(ids)} message(s) to {chat}")
    return {"chat_id": chat, "message_ids": ids}
