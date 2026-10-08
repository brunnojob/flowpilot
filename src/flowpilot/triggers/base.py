"""Base class for trigger runners and the manager that supervises them."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from flowpilot.engine import Engine
    from flowpilot.models import WorkflowSpec

logger = logging.getLogger("flowpilot.triggers")


class TriggerRunner(ABC):
    """A long-running task that fires runs of one workflow."""

    trigger_type: ClassVar[str]

    def __init__(self, engine: Engine, workflow: WorkflowSpec) -> None:
        self.engine = engine
        self.workflow = workflow
        self.next_fire: datetime | None = None

    @abstractmethod
    async def run(self) -> None:
        """Run forever, calling :meth:`fire` when the trigger condition is met."""

    async def fire(self, payload: Any) -> str | None:
        """Submit a run; errors are logged, never raised (triggers must survive)."""
        try:
            run_id = await self.engine.submit(self.workflow.name, self.trigger_type, payload)
        except Exception:
            logger.exception("failed to start %s", self.workflow.name)
            return None
        logger.info(
            "triggered run", extra={"workflow": self.workflow.name, "trigger": self.trigger_type}
        )
        return run_id


class TriggerManager:
    """Starts/stops trigger runners according to each workflow's enabled state."""

    def __init__(self, engine: Engine) -> None:
        from flowpilot.triggers.cron import CronRunner, IntervalRunner
        from flowpilot.triggers.feed import FeedRunner
        from flowpilot.triggers.filewatch import FileRunner

        self.engine = engine
        self.runner_types: dict[str, type[TriggerRunner]] = {
            "cron": CronRunner,
            "interval": IntervalRunner,
            "file": FileRunner,
            "feed": FeedRunner,
        }
        self._runners: dict[str, tuple[TriggerRunner, asyncio.Task[None]]] = {}

    async def start(self) -> None:
        for name in list(self.engine.workflows):
            self.sync(name)

    def sync(self, name: str) -> None:
        """Start or stop the runner for ``name`` to match its enabled state."""
        wf = self.engine.workflows.get(name)
        enabled = wf is not None and self.engine.is_enabled(name)
        running = name in self._runners
        if enabled and not running and wf is not None:
            cls = self.runner_types.get(wf.trigger.type)
            if cls is None:
                return
            runner = cls(self.engine, wf)
            task = asyncio.create_task(self._supervise(runner), name=f"trigger-{name}")
            self._runners[name] = (runner, task)
        elif not enabled and running:
            _, task = self._runners.pop(name)
            task.cancel()

    async def _supervise(self, runner: TriggerRunner) -> None:
        backoff = 1.0
        while True:
            try:
                await runner.run()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("trigger for %s crashed; restarting", runner.workflow.name)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

    async def stop(self) -> None:
        tasks = [task for _, task in self._runners.values()]
        self._runners.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def next_fire(self, name: str) -> datetime | None:
        entry = self._runners.get(name)
        return entry[0].next_fire if entry else None

    def is_active(self, name: str) -> bool:
        return name in self._runners
