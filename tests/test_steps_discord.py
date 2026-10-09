from __future__ import annotations

import json

import httpx
import pytest
import respx

WEBHOOK = "https://discord.com/api/webhooks/123/SECRET"
MESSAGE = {"id": "456", "channel_id": "789"}


@pytest.fixture(autouse=True)
def discord_env(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)


@respx.mock
async def test_send_message_and_embeds(run_step):
    route = respx.post(WEBHOOK, params={"wait": "true"}).mock(
        return_value=httpx.Response(200, json=MESSAGE)
    )
    rec = await run_step(
        "discord",
        {
            "content": "Hello {{ trigger.name }}",
            "embeds": [{"title": "{{ trigger.name }}", "color": 5763719}],
            "username": "flowpilot",
            "avatar_url": "https://example.com/avatar.png",
        },
        payload={"name": "Discord"},
    )
    assert rec["status"] == "success"
    assert rec["output"] == {"message_id": "456", "channel_id": "789"}
    assert json.loads(route.calls[0].request.content) == {
        "content": "Hello Discord",
        "embeds": [{"title": "Discord", "color": 5763719}],
        "username": "flowpilot",
        "avatar_url": "https://example.com/avatar.png",
        "allowed_mentions": {"parse": []},
    }


@respx.mock
async def test_override_webhook_and_preserve_query(run_step):
    url = "http://discord.local/api/webhooks/123/OTHER?thread_id=111&wait=false"
    route = respx.post("http://discord.local/api/webhooks/123/OTHER").mock(
        return_value=httpx.Response(200, json=MESSAGE)
    )
    await run_step("discord", {"webhook_url": url, "content": "x"})
    assert dict(route.calls[0].request.url.params) == {"thread_id": "111", "wait": "true"}


@respx.mock
async def test_embed_only_and_mentions(run_step):
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(200, json=MESSAGE))
    await run_step(
        "discord",
        {
            "embeds": [{"description": "Backup complete"}],
            "allowed_mentions": {"parse": ["users"]},
            "thread_id": 321,
        },
    )
    payload = json.loads(route.calls[0].request.content)
    assert "content" not in payload
    assert payload["allowed_mentions"] == {"parse": ["users"]}
    assert route.calls[0].request.url.params["thread_id"] == "321"


@respx.mock
async def test_content_at_limit_and_no_content_response(run_step):
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    rec = await run_step("discord", {"content": "x" * 2000})
    assert rec["status"] == "success"
    assert rec["output"] == {"message_id": None, "channel_id": None}
    assert len(json.loads(route.calls[0].request.content)["content"]) == 2000


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, "provide content or embeds"),
        ({"content": "", "embeds": []}, "provide content or embeds"),
        ({"content": 123}, "content must be a string"),
        ({"content": "x" * 2001}, "at most 2000"),
        ({"embeds": {}}, "embeds must be a list"),
        ({"embeds": ["invalid"]}, "embeds must be a list"),
        ({"embeds": [{"title": "x"}] * 11}, "at most 10"),
        ({"webhook_url": "file:///SECRET", "content": "x"}, "absolute HTTP(S)"),
        ({"webhook_url": "https:///SECRET", "content": "x"}, "absolute HTTP(S)"),
    ],
)
@respx.mock
async def test_invalid_configuration_is_not_retried(run_step, params, expected):
    rec = await run_step("discord", params, retry=3)
    assert rec["status"] == "failed"
    assert expected in rec["error"]
    assert "SECRET" not in rec["error"]
    assert not respx.calls


async def test_missing_webhook(run_step, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL")
    rec = await run_step("discord", {"content": "x"})
    assert "no webhook URL" in rec["error"]


@pytest.mark.parametrize("status", [400, 401, 404, 302])
@respx.mock
async def test_permanent_errors_and_redirects_are_not_retried(run_step, status):
    route = respx.post(WEBHOOK).mock(
        return_value=httpx.Response(
            status, text=WEBHOOK, headers={"Location": "https://other.test"}
        )
    )
    rec = await run_step("discord", {"content": "x"}, retry=3)
    assert rec["status"] == "failed"
    assert rec["error"] == f"discord: HTTP {status}"
    assert route.call_count == 1


@respx.mock
async def test_transient_errors_retry_without_exposing_webhook(run_step, engine):
    route = respx.post(WEBHOOK).mock(
        side_effect=[
            httpx.Response(429, text=WEBHOOK),
            httpx.Response(503, text=WEBHOOK),
            httpx.ConnectError(f"Cannot connect to {WEBHOOK}"),
            httpx.Response(200, json=MESSAGE),
        ]
    )
    rec = await run_step("discord", {"content": "x"}, retry={"attempts": 4, "delay": 0})
    assert rec["status"] == "success"
    assert route.call_count == 4
    logs = " ".join(line["message"] for line in engine.store.get_logs(rec["run"].run_id))
    assert "SECRET" not in logs
    assert WEBHOOK not in logs
    assert "ConnectError" in logs


@pytest.mark.parametrize("body", ["<html>bad gateway</html>", "[]"])
@respx.mock
async def test_malformed_success_response(run_step, body):
    respx.post(WEBHOOK).mock(return_value=httpx.Response(200, text=body))
    rec = await run_step("discord", {"content": "x"})
    assert rec["status"] == "failed"
    assert "response" in rec["error"]
