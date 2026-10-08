"""Run-time context objects handed to step handlers."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flowpilot import templating
from flowpilot.store import utcnow

if TYPE_CHECKING:
    import httpx

    from flowpilot.config import Settings
    from flowpilot.events import EventBus
    from flowpilot.models import StepSpec, WorkflowSpec
    from flowpilot.store import Store

_py_logger = logging.getLogger("flowpilot.run")


class RunLogger:
    """Logger bound to a run (and optionally a step).

    Every message is persisted to SQLite, published on the event bus (live log
    stream in the dashboard) and forwarded to the ``flowpilot.run`` logger.
    """

    def __init__(
        self,
        store: Store,
        bus: EventBus,
        run_id: str,
        workflow: str,
        step_id: str | None = None,
    ) -> None:
        self._store = store
        self._bus = bus
        self.run_id = run_id
        self.workflow = workflow
        self.step_id = step_id

    def bind(self, step_id: str | None) -> RunLogger:
        """Return a logger bound to ``step_id``."""
        return RunLogger(self._store, self._bus, self.run_id, self.workflow, step_id)

    def log(self, level: str, message: str) -> None:
        ts = utcnow()
        log_id = self._store.add_log(self.run_id, level, message, self.step_id, ts)
        self._bus.publish(
            {
                "type": "log",
                "run_id": self.run_id,
                "workflow": self.workflow,
                "log": {
                    "id": log_id,
                    "ts": ts,
                    "level": level,
                    "step_id": self.step_id,
                    "message": message,
                },
            }
        )
        _py_logger.log(
            getattr(logging, level.upper(), logging.INFO),
            message,
            extra={"run_id": self.run_id[:8], "workflow": self.workflow, "step": self.step_id},
        )

    def debug(self, message: str) -> None:
        self.log("debug", message)

    def info(self, message: str) -> None:
        self.log("info", message)

    def warning(self, message: str) -> None:
        self.log("warning", message)

    def error(self, message: str) -> None:
        self.log("error", message)


@dataclass
class RunContext:
    """Mutable state of a single workflow run."""

    run_id: str
    workflow: WorkflowSpec
    trigger_type: str
    trigger: Any
    started_at: str
    vars: dict[str, Any] = field(default_factory=dict)
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def template_context(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Variables available inside ``{{ ... }}`` templates."""
        ctx: dict[str, Any] = {
            "workflow": {
                "name": self.workflow.name,
                "description": self.workflow.description,
                "tags": self.workflow.tags,
            },
            "run": {
                "id": self.run_id,
                "trigger": self.trigger_type,
                "started_at": self.started_at,
                "error": self.error,
            },
            "trigger": self.trigger,
            "vars": self.vars,
            "env": dict(os.environ),
            "steps": self.steps,
            "state": self.state,
        }
        if extra:
            ctx.update(extra)
        return ctx


@dataclass
class StepContext:
    """Everything a step handler needs: logging, HTTP client, settings, rendering."""

    run: RunContext
    step: StepSpec
    log: RunLogger
    settings: Settings
    http: httpx.AsyncClient
    store: Store
    attempt: int = 1
    extra: dict[str, Any] = field(default_factory=dict)
    _run_steps: Callable[[list[StepSpec]], Awaitable[None]] | None = None

    @property
    def project_dir(self) -> Path:
        return self.settings.project_dir

    @property
    def workflow(self) -> str:
        return self.run.workflow.name

    def resolve_path(self, path: str | os.PathLike[str]) -> Path:
        """Resolve a path relative to the project directory."""
        return self.settings.resolve(Path(path))

    def template_context(self) -> dict[str, Any]:
        return self.run.template_context(self.extra)

    def render(self, value: Any) -> Any:
        """Render a template value against the current run context."""
        return templating.render(value, self.template_context())

    def evaluate(self, condition: Any) -> bool:
        """Evaluate a condition (bool, expression or ``{{ template }}``)."""
        return templating.truthy(condition, self.template_context())

    async def run_steps(self, steps: list[StepSpec]) -> None:
        """Execute nested steps (used by ``branch``)."""
        if self._run_steps is None:  # pragma: no cover - always set by the engine
            raise RuntimeError("nested steps are not supported in this context")
        await self._run_steps(steps)

    def update_state(self, values: dict[str, Any]) -> None:
        """Persist workflow state and make it visible to later steps."""
        self.store.set_state(self.workflow, values)
        self.run.state.update(values)

    def delete_state(self, keys: list[str]) -> None:
        self.store.delete_state(self.workflow, keys)
        for k in keys:
            self.run.state.pop(k, None)
