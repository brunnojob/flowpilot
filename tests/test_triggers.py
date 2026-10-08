from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import respx

from flowpilot.triggers import (
    CronRunner,
    FeedRunner,
    FileRunner,
    IntervalRunner,
    TriggerManager,
    next_cron_time,
)
from flowpilot.triggers import cron as cron_mod
from flowpilot.triggers.filewatch import diff, snapshot

LOG_STEP = [{"id": "a", "type": "log", "with": {"message": "x"}}]


class Recorder:
    def __init__(self, runner):
        self.payloads = []

        async def fake_fire(payload):
            self.payloads.append(payload)
            return "id"

        runner.fire = fake_fire


def test_next_cron_time_respects_timezone():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    nxt = next_cron_time("0 9 * * *", "Asia/Tehran", after=after)
    assert (nxt.hour, nxt.minute) == (9, 0)
    assert nxt.utcoffset() == timedelta(hours=3, minutes=30)
    assert nxt.astimezone(timezone.utc) == datetime(2026, 1, 1, 5, 30, tzinfo=timezone.utc)
    assert next_cron_time("*/5 * * * *").tzinfo is not None


async def test_cron_runner_fires(engine, add_wf, monkeypatch):
    wf = add_wf({"trigger": {"type": "cron", "cron": "* * * * *"}, "steps": LOG_STEP})
    calls = []

    def fake_next(expr, tz=None, after=None):
        calls.append(after)
        return datetime.now(timezone.utc) + timedelta(milliseconds=20)

    monkeypatch.setattr(cron_mod, "next_cron_time", fake_next)
    runner = CronRunner(engine, wf)
    rec = Recorder(runner)
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.15)
    task.cancel()
    assert len(rec.payloads) >= 2
    assert "scheduled_at" in rec.payloads[0]
    assert runner.next_fire is not None


async def test_interval_runner_run_on_start(engine, add_wf, monkeypatch):
    wf = add_wf(
        {"trigger": {"type": "interval", "seconds": 1, "run_on_start": True}, "steps": LOG_STEP}
    )
    runner = IntervalRunner(engine, wf)
    rec = Recorder(runner)
    real_sleep = asyncio.sleep

    async def fast_sleep(_s):
        await real_sleep(0.01)

    monkeypatch.setattr(cron_mod.asyncio, "sleep", fast_sleep)
    task = asyncio.create_task(runner.run())
    await real_sleep(0.08)
    task.cancel()
    assert len(rec.payloads) >= 2


def test_snapshot_and_diff(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "b.log").write_text("1")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_text("1")
    snap = snapshot(tmp_path, ["*.txt"])
    assert sorted(os.path.basename(p) for p in snap) == ["a.txt", "c.txt"]
    assert len(snapshot(tmp_path, ["*.txt"], recursive=False)) == 1
    assert len(snapshot(tmp_path / "a.txt", ["*"])) == 1
    assert snapshot(tmp_path / "missing", ["*"]) == {}
    old = {"x": (1.0, 1), "y": (1.0, 1)}
    new = {"x": (2.0, 1), "z": (1.0, 1)}
    assert diff(old, new) == [("modified", "x"), ("deleted", "y"), ("created", "z")]


async def test_file_runner_detects_changes(engine, add_wf, settings):
    inbox = settings.project_dir / "inbox"
    inbox.mkdir()
    (inbox / "old.csv").write_text("1")
    wf = add_wf(
        {
            "trigger": {
                "type": "file",
                "path": "inbox",
                "patterns": ["*.csv"],
                "events": ["created", "modified", "deleted"],
            },
            "steps": LOG_STEP,
        }
    )
    runner = FileRunner(engine, wf)
    rec = Recorder(runner)
    assert await runner.poll_once() == []  # baseline
    (inbox / "new.csv").write_text("x")
    (inbox / "ignored.txt").write_text("x")
    old = inbox / "old.csv"
    old.write_text("changed!")
    os.utime(old, (time.time() + 5, time.time() + 5))
    changes = await runner.poll_once()
    assert sorted(e for e, _ in changes) == ["created", "modified"]
    (inbox / "new.csv").unlink()
    changes = await runner.poll_once()
    assert changes[0][0] == "deleted"
    assert {p["name"] for p in rec.payloads} == {"new.csv", "old.csv"}
    assert rec.payloads[0]["suffix"] == ".csv"


FEED_V1 = """<?xml version="1.0"?><rss version="2.0"><channel><title>Blog</title><link>https://blog.test</link>
<item><title>First</title><link>https://blog.test/1</link><guid>1</guid><description>&lt;p&gt;one&lt;/p&gt;</description></item>
</channel></rss>"""
FEED_V2 = FEED_V1.replace(
    "<item>",
    "<item><title>Third</title><link>https://blog.test/3</link><guid>3</guid></item>"
    "<item><title>Second</title><link>https://blog.test/2</link><guid>2</guid><category>py</category></item><item>",
    1,
)


@respx.mock
async def test_feed_runner_skip_initial_then_fire_new(engine, add_wf):
    route = respx.get("https://blog.test/rss").mock(
        side_effect=[
            httpx.Response(200, text=FEED_V1),
            httpx.Response(200, text=FEED_V2),
            httpx.Response(200, text=FEED_V2),
        ]
    )
    wf = add_wf({"trigger": {"type": "feed", "url": "https://blog.test/rss"}, "steps": LOG_STEP})
    runner = FeedRunner(engine, wf)
    rec = Recorder(runner)
    assert await runner.poll_once() == []
    fired = await runner.poll_once()
    assert [p["entry"]["title"] for p in fired] == ["Second", "Third"]  # oldest first
    assert fired[0]["feed"] == {"title": "Blog", "link": "https://blog.test"}
    assert fired[0]["entry"]["tags"] == ["py"]
    assert await runner.poll_once() == []
    assert route.call_count == 3
    assert len(rec.payloads) == 2


@respx.mock
async def test_feed_runner_initial_fire_and_errors(engine, add_wf):
    respx.get("https://blog.test/rss").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, text=FEED_V1)]
    )
    wf = add_wf(
        {
            "trigger": {"type": "feed", "url": "https://blog.test/rss", "initial": "fire"},
            "steps": LOG_STEP,
        }
    )
    runner = FeedRunner(engine, wf)
    Recorder(runner)
    assert await runner.poll_once() == []  # HTTP error is logged, not raised
    fired = await runner.poll_once()
    assert fired[0]["entry"]["summary"] == "<p>one</p>"


async def test_fire_submits_real_run(engine, add_wf):
    wf = add_wf({"trigger": {"type": "interval", "seconds": 60}, "steps": LOG_STEP})
    runner = IntervalRunner(engine, wf)
    run_id = await runner.fire({"k": 1})
    result = await engine.wait(run_id)
    assert result.ok
    assert engine.store.get_run(run_id)["trigger_type"] == "interval"
    engine.workflows.pop("test")
    assert await runner.fire({}) is None


async def test_trigger_manager_sync(engine, add_wf):
    add_wf({"name": "tick", "trigger": {"type": "interval", "seconds": 3600}, "steps": LOG_STEP})
    add_wf({"name": "manual", "steps": LOG_STEP})
    add_wf(
        {
            "name": "off",
            "enabled": False,
            "trigger": {"type": "interval", "seconds": 3600},
            "steps": LOG_STEP,
        }
    )
    manager = TriggerManager(engine)
    await manager.start()
    await asyncio.sleep(0.01)
    assert manager.is_active("tick")
    assert not manager.is_active("manual")
    assert not manager.is_active("off")
    assert manager.next_fire("tick") is not None
    assert manager.next_fire("manual") is None
    engine.set_enabled("tick", False)
    manager.sync("tick")
    assert not manager.is_active("tick")
    engine.set_enabled("off", True)
    manager.sync("off")
    assert manager.is_active("off")
    await manager.stop()
    assert not manager.is_active("off")


async def test_trigger_manager_restarts_crashed_runner(engine, add_wf, monkeypatch):
    wf = add_wf({"trigger": {"type": "interval", "seconds": 3600}, "steps": LOG_STEP})
    manager = TriggerManager(engine)
    attempts = {"n": 0}

    class Crashy(IntervalRunner):
        async def run(self):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("crash")

    real_sleep = asyncio.sleep

    async def no_sleep(_s):
        await real_sleep(0)

    monkeypatch.setattr("flowpilot.triggers.base.asyncio.sleep", no_sleep)
    await manager._supervise(Crashy(engine, wf))
    assert attempts["n"] == 2
