from __future__ import annotations

import json

import httpx
import pytest
import respx

from flowpilot.steps.telegram import split_message

API = "https://api.telegram.org/botTOKEN"


@pytest.fixture(autouse=True)
def tg_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")


def ok(message_id=1):
    return httpx.Response(200, json={"ok": True, "result": {"message_id": message_id}})


@respx.mock
async def test_send_message(run_step):
    route = respx.post(f"{API}/sendMessage").mock(return_value=ok(7))
    rec = await run_step("telegram", {"text": "<b>hi</b>"})
    assert rec["status"] == "success"
    assert rec["output"] == {"chat_id": "42", "message_ids": [7]}
    body = json.loads(route.calls[0].request.content)
    assert body["chat_id"] == "42"
    assert body["text"] == "<b>hi</b>"
    assert body["parse_mode"] == "HTML"
    assert body["link_preview_options"] == {"is_disabled": True}
    assert body["disable_notification"] is False


@respx.mock
async def test_long_messages_are_split(run_step):
    route = respx.post(f"{API}/sendMessage").mock(side_effect=[ok(1), ok(2)])
    text = ("line\n" * 1000).strip()  # ~5000 chars
    rec = await run_step("telegram", {"text": text, "chat_id": "@chan", "parse_mode": None})
    assert rec["output"]["message_ids"] == [1, 2]
    first = json.loads(route.calls[0].request.content)
    assert "parse_mode" not in first
    assert first["chat_id"] == "@chan"


def test_split_message():
    assert split_message("short") == ["short"]
    parts = split_message("a" * 9000)
    assert [len(p) for p in parts] == [4096, 4096, 808]
    parts = split_message("x" * 3000 + "\n" + "y" * 3000)
    assert len(parts) == 2
    assert all(len(p) <= 4096 for p in parts)


@respx.mock
async def test_send_local_document(run_step, settings):
    (settings.project_dir / "report.txt").write_text("data")
    route = respx.post(f"{API}/sendDocument").mock(return_value=ok(3))
    rec = await run_step("telegram", {"document": "report.txt", "caption": "Report"})
    assert rec["output"]["message_ids"] == [3]
    req = route.calls[0].request
    assert b'filename="report.txt"' in req.content
    assert b"Report" in req.content


@respx.mock
async def test_send_photo_by_url(run_step):
    route = respx.post(f"{API}/sendPhoto").mock(return_value=ok(4))
    await run_step("telegram", {"photo": "https://img.test/a.png", "text": "cap", "silent": True})
    body = json.loads(route.calls[0].request.content)
    assert body["photo"] == "https://img.test/a.png"
    assert body["caption"] == "cap"
    assert body["disable_notification"] is True


@respx.mock
async def test_custom_method(run_step):
    route = respx.post(f"{API}/sendPoll").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"poll": 1}})
    )
    rec = await run_step(
        "telegram", {"method": "sendPoll", "payload": {"chat_id": 1, "question": "?"}}
    )
    assert rec["output"] == {"result": {"poll": 1}}
    assert json.loads(route.calls[0].request.content)["question"] == "?"


@respx.mock
async def test_api_errors(run_step):
    respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(
            400, json={"ok": False, "error_code": 400, "description": "chat not found"}
        )
    )
    rec = await run_step("telegram", {"text": "x"}, retry=3)
    assert "400 chat not found" in rec["error"]
    assert rec["run"].status == "failed"


@respx.mock
async def test_rate_limit_retryable_and_token_redacted(run_step, engine):
    route = respx.post(f"{API}/sendMessage").mock(
        side_effect=[
            httpx.Response(
                429, json={"ok": False, "error_code": 429, "description": "Too Many Requests"}
            ),
            httpx.ConnectError(
                "failed to connect to https://api.telegram.org/botTOKEN/sendMessage"
            ),
            httpx.Response(502, text="<html>bad gateway</html>"),
        ]
    )
    rec = await run_step("telegram", {"text": "x"}, retry={"attempts": 3, "delay": 0})
    assert route.call_count == 3
    assert "non-JSON" in rec["error"]
    logs = " ".join(line["message"] for line in engine.store.get_logs(rec["run"].run_id))
    assert "TOKEN" not in logs
    assert "<token>" in logs


async def test_missing_configuration(run_step, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    rec = await run_step("telegram", {"text": "x"})
    assert "no bot token" in rec["error"]
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    rec = await run_step("telegram", {"text": "x"})
    assert "no chat_id" in rec["error"]
    rec = await run_step("telegram", {"chat_id": 1})
    assert "provide text" in rec["error"]


@respx.mock
async def test_custom_api_base(run_step, engine):
    engine.settings.telegram_api_base = "http://tg.local/"
    route = respx.post("http://tg.local/botTOKEN/sendMessage").mock(return_value=ok())
    await run_step("telegram", {"text": "x"})
    assert route.called
