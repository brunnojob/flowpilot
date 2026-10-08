from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from flowpilot.config import Settings
from flowpilot.engine import Engine
from flowpilot.loader import parse_workflow
from flowpilot.models import WorkflowSpec
from flowpilot.registry import StepRegistry, default_registry

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(project_dir=tmp_path, database=tmp_path / "fp.db", history_days=0)


@pytest.fixture
def registry() -> StepRegistry:
    return default_registry.clone()


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        await asyncio.sleep(0)


@pytest.fixture
async def engine(settings: Settings, registry: StepRegistry) -> AsyncIterator[Engine]:
    eng = Engine(settings, registry=registry)
    eng._sleep = SleepRecorder()  # type: ignore[assignment]
    await eng.start()
    yield eng
    await eng.close()
    eng.store.close()


@pytest.fixture
def make_wf(registry: StepRegistry):
    def factory(data: dict[str, Any]) -> WorkflowSpec:
        data = {"name": "test", **data}
        return parse_workflow(data, "<test>", registry)

    return factory


@pytest.fixture
def add_wf(engine: Engine, make_wf):
    def factory(data: dict[str, Any]) -> WorkflowSpec:
        wf = make_wf(data)
        engine.workflows[wf.name] = wf
        return wf

    return factory


@pytest.fixture
def run_step(engine, add_wf):
    """Run a single step in a throwaway workflow and return its record."""
    counter = {"n": 0}

    async def runner(
        type_: str, with_: dict[str, Any] | None = None, payload: Any = None, **kw: Any
    ):
        counter["n"] += 1
        name = f"step-test-{counter['n']}"
        add_wf({"name": name, "steps": [{"id": "s", "type": type_, "with": with_ or {}, **kw}]})
        result = await engine.run(name, payload=payload)
        rec = dict(result.steps["s"])
        rec["run"] = result
        return rec

    return runner
