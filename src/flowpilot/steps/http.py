"""``http`` — make an HTTP request."""

from __future__ import annotations

import time
from typing import Any

import httpx

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError, StepError
from flowpilot.registry import step


@step("http")
async def http_request(
    ctx: StepContext,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: Any = None,
    data: dict[str, Any] | str | None = None,
    timeout: float = 30.0,
    expect_status: int | list[int] | None = None,
    fail_on_error: bool = True,
    follow_redirects: bool = True,
    auth: list[str] | None = None,
) -> dict[str, Any]:
    """Send an HTTP request and return status, headers, parsed JSON and text.

    Fails (and is retryable) on network errors and, unless ``fail_on_error`` is
    false, on 4xx/5xx responses or a status not in ``expect_status``.
    """
    if not url or not str(url).startswith(("http://", "https://")):
        raise StepConfigError(f"http: url must start with http:// or https:// (got {url!r})")
    basic = None
    if auth is not None:
        if len(auth) != 2:
            raise StepConfigError("http: auth must be [username, password]")
        basic = (str(auth[0]), str(auth[1]))
    t0 = time.monotonic()
    try:
        resp = await ctx.http.request(
            method.upper(),
            url,
            headers=headers,
            params=params,
            json=json,
            data=data if isinstance(data, dict) else None,
            content=data if isinstance(data, str) else None,
            timeout=timeout,
            follow_redirects=follow_redirects,
            auth=basic,
        )
    except httpx.HTTPError as exc:
        raise StepError(f"{type(exc).__name__}: {exc or 'request failed'}") from exc
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    body: Any = None
    ctype = resp.headers.get("content-type", "")
    if "json" in ctype:
        try:
            body = resp.json()
        except ValueError:
            body = None
    result = {
        "status": resp.status_code,
        "ok": resp.is_success,
        "url": str(resp.url),
        "headers": dict(resp.headers),
        "json": body,
        "text": resp.text if body is None else None,
        "elapsed_ms": elapsed_ms,
    }
    ctx.log.info(f"{method.upper()} {url} → {resp.status_code} ({elapsed_ms} ms)")

    if expect_status is not None:
        expected = [expect_status] if isinstance(expect_status, int) else list(expect_status)
        if resp.status_code not in expected and fail_on_error:
            raise StepError(f"unexpected status {resp.status_code} (expected {expected})")
    elif fail_on_error and not resp.is_success:
        retryable = resp.status_code >= 500 or resp.status_code == 429
        snippet = resp.text[:200].replace("\n", " ")
        raise StepError(f"HTTP {resp.status_code}: {snippet}", retryable=retryable)
    return result
