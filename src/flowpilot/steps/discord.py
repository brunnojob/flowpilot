"""``discord`` — send messages and embeds through an incoming Discord webhook.

Set ``DISCORD_WEBHOOK_URL`` or pass ``webhook_url`` for an individual step.
The webhook URL contains a secret; errors and outputs never include it.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError, StepError
from flowpilot.registry import step


@step("discord")
async def discord(
    ctx: StepContext,
    content: str | None = None,
    embeds: list[dict[str, Any]] | None = None,
    webhook_url: str | None = None,
    username: str | None = None,
    avatar_url: str | None = None,
    allowed_mentions: dict[str, Any] | None = None,
    thread_id: str | int | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Post content and/or embeds and return the created message and channel IDs."""
    webhook = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        raise StepConfigError(
            "discord: no webhook URL (set DISCORD_WEBHOOK_URL or pass webhook_url)"
        )
    try:
        url = httpx.URL(webhook)
    except (httpx.InvalidURL, TypeError):
        raise StepConfigError("discord: webhook_url must be an absolute HTTP(S) URL") from None
    if url.scheme not in ("http", "https") or not url.host:
        raise StepConfigError("discord: webhook_url must be an absolute HTTP(S) URL")
    if content is not None and (not isinstance(content, str) or len(content) > 2000):
        raise StepConfigError("discord: content must be a string of at most 2000 characters")
    if embeds is not None and (
        not isinstance(embeds, list)
        or len(embeds) > 10
        or any(not isinstance(embed, dict) for embed in embeds)
    ):
        raise StepConfigError("discord: embeds must be a list of at most 10 objects")
    if not content and not embeds:
        raise StepConfigError("discord: provide content or embeds")

    payload: dict[str, Any] = {
        "allowed_mentions": allowed_mentions if allowed_mentions is not None else {"parse": []}
    }
    for key, value in (
        ("content", content),
        ("embeds", embeds),
        ("username", username),
        ("avatar_url", avatar_url),
    ):
        if value is not None:
            payload[key] = value
    # Request confirmation: Discord may silently discard a message with wait=false.
    params = {"wait": "true"}
    if thread_id is not None:
        params["thread_id"] = str(thread_id)
    url = url.copy_merge_params(params)
    try:
        response = await ctx.http.post(url, json=payload, timeout=timeout, follow_redirects=False)
    except httpx.HTTPError as exc:
        # Exception strings and response bodies can echo the webhook token.
        raise StepError(f"discord: {type(exc).__name__} (webhook request failed)") from None
    if not response.is_success:
        raise StepError(
            f"discord: HTTP {response.status_code}",
            retryable=response.status_code == 429 or response.status_code >= 500,
        )
    if response.status_code == 204:
        message: dict[str, Any] = {}
    else:
        try:
            message = response.json()
        except ValueError:
            raise StepError("discord: invalid JSON response") from None
        if not isinstance(message, dict):
            raise StepError("discord: expected a message object in the response")
    ctx.log.info("sent Discord webhook message")
    return {"message_id": message.get("id"), "channel_id": message.get("channel_id")}
