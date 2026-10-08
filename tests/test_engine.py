from __future__ import annotations

import asyncio

import pytest

from flowpilot.errors import StepError
from flowpilot.events import EventBus


def log(message="x", **kw):
    return {"type": "log", "with": {"message": message}, **kw}


async def test_sequential_steps_and_templating(engine, add_wf):
    add_wf(
        {
            "vars": {"who": "{{ trigger.name or 'world' }}"},
            "steps": [
                {"id": "a", "type": "transform", "with": {"value": {"n": 2}}},
                {"id": "b", "type": "transform", "with": {"value": "{{ steps.a.output.n * 21 }}"}},
                {
                    "id": "c",
                    "type": "transform",
                    "with": {"template": "Hi {{ vars.who }}: {{ steps.b.output }}"},
                },
            ],
        }
    )
    result = await engine.run("test", payload={"name": "Reza"})
    assert result.ok
    assert result.steps["b"]["output"] == 42
    assert result.steps["c"]["output"] == "Hi Reza: 42"
    run = engine.store.get_run(result.run_id)
    assert run["status"] == "success"
    assert [s["step_id"] for s in run["steps"]] == ["a", "b", "c"]
    assert run["trigger_payload"] == {"name": "Reza"}
    logs = engine.store.get_logs(result.run_id)
    assert logs[0]["message"].startswith("run started")
    assert logs[-1]["message"].startswith("run success")


async def test_if_condition_skips_step(engine, add_wf):
    add_wf({"steps": [log(id="a", **{"if": "{{ 1 > 2 }}"}), log(id="b", **{"if": "1 < 2"})]})
    result = await engine.run("test")
    assert result.steps["a"]["status"] == "skipped"
    assert result.steps["b"]["status"] == "success"


async def test_retries_with_backoff_then_success(engine, add_wf, registry):
    calls = {"n": 0}

    @registry.step("flaky")
    async def flaky(ctx, fail_times: int):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise RuntimeError(f"boom {calls['n']}")
        return {"attempt": ctx.attempt}

    add_wf(
        {
            "steps": [
                {
                    "id": "f",
                    "type": "flaky",
                    "with": {"fail_times": 2},
                    "retry": {"attempts": 3, "delay": 1, "backoff": 3},
                }
            ]
        }
    )
    result = await engine.run("test")
    assert result.ok
    assert result.steps["f"]["output"] == {"attempt": 3}
    assert engine._sleep.calls == [1, 3]
    assert engine.store.get_run(result.run_id)["steps"][0]["attempts"] == 3


async def test_retries_exhausted_fails_run(engine, add_wf, registry):
    @registry.step("always_fail")
    def always_fail(ctx):
        raise StepError("nope")

    add_wf({"steps": [{"id": "f", "type": "always_fail", "retry": 2}, log(id="after")]})
    result = await engine.run("test")
    assert result.status == "failed"
    assert "nope" in result.error
    assert "after" not in result.steps
    assert len(engine._sleep.calls) == 1


async def test_non_retryable_errors_are_not_retried(engine, add_wf, registry):
    @registry.step("fatal")
    def fatal(ctx):
        raise StepError("bad input", retryable=False)

    add_wf({"steps": [{"id": "f", "type": "fatal", "retry": 5}]})
    result = await engine.run("test")
    assert result.status == "failed"
    assert engine._sleep.calls == []


async def test_unknown_parameter_is_config_error(engine, add_wf):
    wf = add_wf({"steps": [log(id="a")]})
    wf.steps[0].with_["bogus"] = 1
    result = await engine.run("test")
    assert result.status == "failed"
    assert "unknown parameter" in result.error


async def test_step_timeout(engine, add_wf, registry):
    @registry.step("slow")
    async def slow(ctx):
        await asyncio.sleep(5)

    add_wf({"steps": [{"id": "s", "type": "slow", "timeout": 0.05}]})
    result = await engine.run("test")
    assert result.status == "failed"
    assert "timed out after 0.05s" in result.error


async def test_workflow_timeout(engine, add_wf, registry):
    @registry.step("slow2")
    async def slow2(ctx):
        await asyncio.sleep(5)

    add_wf({"timeout": 0.05, "steps": [{"id": "s", "type": "slow2"}]})
    result = await engine.run("test")
    assert result.status == "failed"
    assert "workflow timed out" in result.error


async def test_continue_on_error(engine, add_wf, registry):
    @registry.step("err")
    def err(ctx):
        raise ValueError("bad")

    add_wf({"steps": [{"id": "e", "type": "err", "continue_on_error": True}, log(id="next")]})
    result = await engine.run("test")
    assert result.ok
    assert result.steps["e"]["status"] == "failed"
    assert result.steps["e"]["error"] == "ValueError: bad"
    assert result.steps["next"]["status"] == "success"


async def test_on_failure_handlers_see_error(engine, add_wf, registry):
    @registry.step("err2")
    def err2(ctx):
        raise RuntimeError("disk full")

    add_wf(
        {
            "steps": [{"id": "e", "type": "err2"}],
            "on_failure": [
                {"id": "notify", "type": "transform", "with": {"value": "{{ run.error }}"}}
            ],
        }
    )
    result = await engine.run("test")
    assert result.status == "failed"
    assert "disk full" in result.steps["notify"]["output"]


async def test_on_failure_errors_do_not_mask_failure(engine, add_wf, registry):
    @registry.step("err3")
    def err3(ctx):
        raise RuntimeError("x")

    add_wf({"steps": [{"id": "e", "type": "err3"}], "on_failure": [{"id": "e2", "type": "err3"}]})
    result = await engine.run("test")
    assert result.status == "failed"
    assert result.steps["e2"]["status"] == "failed"


async def test_condition_step_stops_run_successfully(engine, add_wf):
    add_wf(
        {
            "steps": [
                {
                    "id": "gate",
                    "type": "condition",
                    "with": {"check": "{{ trigger.go }}", "reason": "no go"},
                },
                log(id="after"),
            ]
        }
    )
    stopped = await engine.run("test", payload={"go": False})
    assert stopped.ok
    assert stopped.steps["gate"]["output"] == {"stopped": True, "reason": "no go"}
    assert "after" not in stopped.steps
    passed = await engine.run("test", payload={"go": True})
    assert passed.steps["after"]["status"] == "success"


async def test_condition_with_free_text_values_and_raw_expressions(engine, add_wf):
    add_wf(
        {
            "steps": [
                {"id": "msg", "type": "condition", "with": {"check": "{{ trigger.message }}"}},
                {
                    "id": "expr",
                    "type": "condition",
                    "with": {"check": "trigger.n > 1", "reason": "n={{ trigger.n }}"},
                },
                log(id="after"),
            ]
        }
    )
    ok = await engine.run("test", payload={"message": "Hi! Is this {weird}?", "n": 2})
    assert ok.steps["after"]["status"] == "success"
    empty = await engine.run("test", payload={"message": "", "n": 2})
    assert empty.ok
    assert "expr" not in empty.steps
    low = await engine.run("test", payload={"message": "x", "n": 0})
    assert low.steps["expr"]["output"]["reason"] == "n=0"


async def test_branch_selects_case_and_default(engine, add_wf):
    add_wf(
        {
            "steps": [
                {
                    "id": "route",
                    "type": "branch",
                    "with": {
                        "cases": [
                            {
                                "when": "trigger.n > 10",
                                "steps": [
                                    {"id": "big", "type": "transform", "with": {"value": "big"}}
                                ],
                            },
                            {
                                "when": "{{ trigger.n > 5 }}",
                                "steps": [
                                    {
                                        "id": "mid",
                                        "type": "transform",
                                        "with": {"value": "{{ trigger.n }}"},
                                    }
                                ],
                            },
                        ],
                        "default": [
                            {"id": "small", "type": "transform", "with": {"value": "small"}}
                        ],
                    },
                },
                {
                    "id": "final",
                    "type": "transform",
                    "with": {"value": "{{ steps.route.output.taken }}"},
                },
            ]
        }
    )
    r1 = await engine.run("test", payload={"n": 50})
    assert r1.steps["big"]["output"] == "big"
    assert r1.steps["final"]["output"] == "case 1"
    r2 = await engine.run("test", payload={"n": 7})
    assert r2.steps["mid"]["output"] == 7
    r3 = await engine.run("test", payload={"n": 1})
    assert r3.steps["small"]["output"] == "small"
    assert r3.steps["final"]["output"] == "default"


async def test_branch_without_match_and_nested_failure(engine, add_wf, registry):
    @registry.step("boom")
    def boom(ctx):
        raise RuntimeError("nested")

    add_wf(
        {
            "steps": [
                {
                    "id": "b",
                    "type": "branch",
                    "with": {
                        "cases": [{"when": "trigger.x", "steps": [{"id": "n", "type": "boom"}]}]
                    },
                    "retry": 3,
                },
            ]
        }
    )
    none = await engine.run("test", payload={"x": False})
    assert none.steps["b"]["output"] == {"taken": None, "index": None}
    failed = await engine.run("test", payload={"x": True})
    assert failed.status == "failed"
    assert "nested" in failed.error
    assert engine._sleep.calls == []  # nested failures are not retried by the branch


async def test_for_each_with_per_item_condition(engine, add_wf):
    add_wf(
        {
            "vars": {"nums": [1, 2, 3, 4]},
            "steps": [
                {
                    "id": "sq",
                    "type": "transform",
                    "for_each": "{{ vars.nums }}",
                    "if": "item % 2 == 0",
                    "with": {"value": "{{ item * item }}"},
                },
                {
                    "id": "idx",
                    "type": "transform",
                    "for_each": ["a", "b"],
                    "with": {"value": "{{ loop.index }}/{{ loop.length }}"},
                },
                {
                    "id": "kv",
                    "type": "transform",
                    "for_each": "{{ {'a': 1} }}",
                    "with": {"value": "{{ item.key }}={{ item.value }}"},
                },
                {
                    "id": "none",
                    "type": "log",
                    "for_each": "{{ steps.missing.output }}",
                    "with": {"message": "x"},
                },
            ],
        }
    )
    result = await engine.run("test")
    assert result.steps["sq"]["output"] == [4, 16]
    assert [r["item"] for r in result.steps["sq"]["results"]] == [2, 4]
    assert result.steps["idx"]["output"] == ["1/2", "2/2"]
    assert result.steps["kv"]["output"] == ["a=1"]
    assert result.steps["none"]["status"] == "success"


async def test_for_each_failures_and_continue(engine, add_wf, registry):
    @registry.step("maybe")
    def maybe(ctx, value: int):
        if value == 2:
            raise RuntimeError("two")
        return value

    add_wf(
        {
            "steps": [
                {
                    "id": "m",
                    "type": "maybe",
                    "for_each": [1, 2, 3],
                    "continue_on_error": True,
                    "with": {"value": "{{ item }}"},
                }
            ]
        }
    )
    result = await engine.run("test")
    assert result.ok
    rec = result.steps["m"]
    assert rec["status"] == "failed"
    assert [r["ok"] for r in rec["results"]] == [True, False, True]
    assert rec["error"] == "RuntimeError: two"

    add_wf(
        {
            "name": "strict",
            "steps": [
                {"id": "m", "type": "maybe", "for_each": [1, 2, 3], "with": {"value": "{{ item }}"}}
            ],
        }
    )
    strict = await engine.run("strict")
    assert strict.status == "failed"
    assert len(strict.steps["m"]["results"]) == 2


async def test_for_each_all_filtered_is_skipped_and_bad_type_fails(engine, add_wf):
    add_wf(
        {
            "steps": [
                {"id": "a", "type": "log", "for_each": [1], "if": "false", "with": {"message": "x"}}
            ]
        }
    )
    assert (await engine.run("test")).steps["a"]["status"] == "skipped"
    add_wf(
        {
            "name": "bad",
            "steps": [{"id": "a", "type": "log", "for_each": "{{ 5 }}", "with": {"message": "x"}}],
        }
    )
    bad = await engine.run("bad")
    assert bad.status == "failed"
    assert "must evaluate to a list" in bad.error


async def test_state_persists_between_runs(engine, add_wf):
    add_wf(
        {
            "steps": [
                {
                    "id": "s",
                    "type": "state",
                    "with": {"set": {"count": "{{ (state.count or 0) + 1 }}"}},
                },
            ]
        }
    )
    await engine.run("test")
    await engine.run("test")
    assert engine.store.get_state("test") == {"count": 2}


async def test_events_are_published(engine, add_wf):
    add_wf({"steps": [log(id="a")]})
    seen = []
    async with engine.bus.subscribe() as queue:
        await engine.run("test")
        while not queue.empty():
            seen.append(queue.get_nowait()["type"])
    assert seen[0] == "run.started"
    assert "step.started" in seen
    assert "step.finished" in seen
    assert "log" in seen
    assert seen[-1] == "run.finished"


async def test_submit_and_wait_and_unknown(engine, add_wf):
    add_wf({"steps": [log(id="a")]})
    run_id = await engine.submit("test")
    assert engine.store.get_run(run_id)["status"] in {"running", "success"}
    result = await engine.wait(run_id)
    assert result is not None
    assert result.ok
    assert await engine.wait("nope") is None
    assert result.to_dict()["steps"]["a"]["status"] == "success"
    from flowpilot.errors import WorkflowNotFound

    with pytest.raises(WorkflowNotFound):
        await engine.submit("missing")


async def test_concurrency_limit_serializes_runs(engine, add_wf, registry):
    active = {"now": 0, "max": 0}

    @registry.step("busy")
    async def busy(ctx):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1

    add_wf({"concurrency": 1, "steps": [{"id": "b", "type": "busy"}]})
    ids = [await engine.submit("test") for _ in range(3)]
    await asyncio.gather(*(engine.wait(i) for i in ids))
    assert active["max"] == 1


async def test_close_cancels_running_runs(settings, registry, make_wf):
    from flowpilot.engine import Engine

    @registry.step("forever")
    async def forever(ctx):
        await asyncio.sleep(60)

    eng = Engine(settings, registry=registry)
    await eng.start()
    eng.workflows["test"] = make_wf({"steps": [{"id": "f", "type": "forever"}]})
    run_id = await eng.submit("test")
    await asyncio.sleep(0.05)
    assert eng.active_runs == [run_id]
    await eng.close()
    assert eng.store.get_run(run_id)["status"] == "cancelled"


async def test_interrupted_runs_marked_failed_on_start(settings, registry):
    from flowpilot.engine import Engine
    from flowpilot.store import Store, utcnow

    store = Store(settings.database)
    store.create_run("r1", "wf", "manual", {}, utcnow())
    eng = Engine(settings, registry=registry, store=store)
    await eng.start()
    assert store.get_run("r1")["status"] == "failed"
    await eng.close()


async def test_enable_overrides_and_webhook_lookup(engine, add_wf):
    add_wf({"name": "hook", "trigger": {"type": "webhook", "path": "in/x"}, "steps": [log(id="a")]})
    assert engine.is_enabled("hook")
    engine.set_enabled("hook", False)
    assert not engine.is_enabled("hook")
    assert engine.find_webhook("/in/x/").name == "hook"
    assert engine.find_webhook("other") is None


async def test_bus_publish_from_thread():
    bus = EventBus()
    loop = asyncio.get_running_loop()
    bus.bind_loop(loop)
    async with bus.subscribe() as queue:
        await asyncio.to_thread(bus.publish, {"type": "x"})
        event = await asyncio.wait_for(queue.get(), 1)
    assert event == {"type": "x"}
    assert bus.subscriber_count == 0


async def test_bus_drops_when_full():
    bus = EventBus(max_queue=1)
    async with bus.subscribe() as queue:
        bus.publish({"n": 1})
        bus.publish({"n": 2})
        assert queue.qsize() == 1
