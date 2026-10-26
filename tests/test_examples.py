"""Run the Jalali report example with a fixed clock and mocked HTTP/Telegram APIs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from flowpilot.loader import load_yaml_file
from flowpilot.templating import ENV

EXAMPLE = Path(__file__).resolve().parent.parent / "examples/workflows/daily-report-jalali.yaml"


@pytest.mark.parametrize(
    ("status", "expected_status", "expected_code"),
    [(200, "در دسترس", "۲۰۰"), (503, "خطای HTTP", "۵۰۳")],
)
@respx.mock
async def test_daily_report_jalali(engine, monkeypatch, status, expected_status, expected_code):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST_TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    engine.settings.telegram_api_base = "https://telegram.test"
    clock_zones = []

    def fixed_now(tz):
        clock_zones.append(tz)
        return datetime(2026, 3, 21, 9, tzinfo=ZoneInfo(tz))

    monkeypatch.setitem(ENV.globals, "now", fixed_now)
    wf = load_yaml_file(EXAMPLE, engine.registry)
    assert wf.trigger.type == "cron"
    assert wf.trigger.cron == "0 9 * * *"
    assert wf.trigger.timezone == "Asia/Tehran"
    wf.vars["url"] = "https://example.com/?a=1&b=2"
    engine.workflows[wf.name] = wf
    check = respx.get(wf.vars["url"]).mock(return_value=httpx.Response(status))
    telegram = respx.post("https://telegram.test/botTEST_TOKEN/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
    )

    result = await engine.run(wf.name)

    assert result.status == "success"
    assert check.call_count == telegram.call_count == 1
    assert clock_zones == ["Asia/Tehran"]
    message = json.loads(telegram.calls[0].request.content)
    assert message["chat_id"] == "42"
    assert message["parse_mode"] == "HTML"
    assert "۰۱ فروردین ۱۴۰۵" in message["text"]
    assert expected_status in message["text"]
    assert f"کد HTTP: {expected_code}" in message["text"]
    assert "https://example.com/?a=1&amp;b=2" in message["text"]
    elapsed = str(result.steps["check"]["output"]["elapsed_ms"]).translate(
        str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    )
    assert f"زمان پاسخ: {elapsed} میلی‌ثانیه" in message["text"]
    assert result.steps["send"]["output"]["message_ids"] == [7]
