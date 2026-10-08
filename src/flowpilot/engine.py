"""The asynchronous workflow execution engine.

The engine owns the loaded workflows, executes runs (sequential steps with
per-step timeouts, retries with exponential backoff, ``if`` conditions,
``for_each`` loops and ``on_failure`` handlers), persists everything to the
:class:`~flowpilot.store.Store` and publishes live events on the
:class:`~flowpilot.events.EventBus`.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import httpx

from flowpilot import __version__, templating
from flowpilot.config import Settings
from flowpilot.context import RunContext, RunLogger, StepContext
from flowpilot.errors import StepConfigError, StepError, StopRun, WorkflowNotFound
from flowpilot.events import EventBus
from flowpilot.models import RetryPolicy, StepSpec, WorkflowSpec
from flowpilot.registry import StepRegistry, default_registry
from flowpilot.store import Store, utcnow

logger = logging.getLogger("flowpilot.engine")

# Steps whose ``with`` is passed unrendered: they evaluate expressions themselves.
RAW_PARAM_STEPS = {"branch", "condition"}


class StepFailure(Exception):
    """Internal: a step failed and the run must stop."""

    def __init__(self, step_id: str, message: str) -> None:
        super().__init__(f"step '{step_id}' failed: {message}")
        self.step_id = step_id
        self.message = message


@dataclass
class RunResult:
    """Outcome of a finished run."""

    run_id: str
    workflow: str
    status: str
    duration_ms: int
    error: str | None = None
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow": self.workflow,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "steps": {
                k: {"status": v.get("status"), "error": v.get("error")}
                for k, v in self.steps.items()
            },
        }


class Engine:
    """Executes workflows and keeps track of in-flight runs."""

    def __init__(
        self,
        settings: Settings,
        *,
        store: Store | None = None,
        registry: StepRegistry | None = None,
        bus: EventBus | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or Store(settings.database, max_output_chars=settings.max_output_chars)
        self.registry = registry or default_registry
        self.bus = bus or EventBus()
        self._http = http
        self._owns_http = http is None
        self.workflows: dict[str, WorkflowSpec] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._tasks: dict[str, asyncio.Task[RunResult]] = {}
        self._sleep = asyncio.sleep
        self._started = False

    # ----------------------------------------------------------- lifecycle

    @property
    def http(self) -> httpx.AsyncClient:
        """Shared HTTP client (created lazily)."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                follow_redirects=True,
                headers={"User-Agent": f"{self.settings.http_user_agent}/{__version__}"},
            )
        return self._http

    async def start(self) -> None:
        """Bind to the running loop and recover from unclean shutdowns."""
        if self._started:
            return
        self._started = True
        self.bus.bind_loop(asyncio.get_running_loop())
        interrupted = await asyncio.to_thread(self.store.mark_interrupted)
        if interrupted:
            logger.warning("marked %d interrupted run(s) as failed", interrupted)
        if self.settings.history_days > 0:
            await asyncio.to_thread(self.store.prune, self.settings.history_days)

    async def close(self) -> None:
        """Cancel in-flight runs and release resources."""
        tasks = [t for t in self._tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None
        self._started = False

    # ----------------------------------------------------------- workflows

    def set_workflows(self, workflows: list[WorkflowSpec]) -> None:
        self.workflows = {wf.name: wf for wf in workflows}

    def get(self, name: str) -> WorkflowSpec:
        try:
            return self.workflows[name]
        except KeyError:
            raise WorkflowNotFound(f"workflow {name!r} not found") from None

    def is_enabled(self, name: str) -> bool:
        overrides = self.store.get_enabled_overrides()
        return overrides.get(name, self.get(name).enabled)

    def set_enabled(self, name: str, enabled: bool) -> None:
        self.get(name)
        self.store.set_enabled(name, enabled)
        self.bus.publish({"type": "workflow.updated", "workflow": name, "enabled": enabled})

    def find_webhook(self, path: str) -> WorkflowSpec | None:
        path = path.strip("/")
        for wf in self.workflows.values():
            if wf.webhook_path == path:
                return wf
        return None

    @property
    def active_runs(self) -> list[str]:
        return [rid for rid, t in self._tasks.items() if not t.done()]

    # ---------------------------------------------------------------- runs

    async def submit(self, name: str, trigger_type: str = "manual", payload: Any = None) -> str:
        """Start a run in the background and return its id immediately."""
        wf = self.get(name)
        run_id = uuid.uuid4().hex
        started_at = utcnow()
        await asyncio.to_thread(
            self.store.create_run, run_id, wf.name, trigger_type, payload, started_at
        )
        task = asyncio.create_task(
            self._execute(wf, trigger_type, payload, run_id, started_at),
            name=f"flowpilot-run-{run_id[:8]}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(partial(self._forget, run_id))
        return run_id

    def _forget(self, run_id: str, _task: asyncio.Task[RunResult]) -> None:
        self._tasks.pop(run_id, None)

    async def wait(self, run_id: str) -> RunResult | None:
        """Wait for an in-flight run started with :meth:`submit`."""
        task = self._tasks.get(run_id)
        return await task if task else None

    async def run(self, name: str, trigger_type: str = "manual", payload: Any = None) -> RunResult:
        """Execute a workflow and wait for the result."""
        run_id = await self.submit(name, trigger_type, payload)
        task = self._tasks.get(run_id)
        assert task is not None
        return await task

    def _semaphore(self, wf: WorkflowSpec) -> asyncio.Semaphore:
        sem = self._semaphores.get(wf.name)
        if sem is None:
            sem = self._semaphores[wf.name] = asyncio.Semaphore(wf.concurrency)
        return sem

    async def _execute(
        self, wf: WorkflowSpec, trigger_type: str, payload: Any, run_id: str, started_at: str
    ) -> RunResult:
        async with self._semaphore(wf):
            return await self._execute_locked(wf, trigger_type, payload, run_id, started_at)

    async def _execute_locked(
        self, wf: WorkflowSpec, trigger_type: str, payload: Any, run_id: str, started_at: str
    ) -> RunResult:
        t0 = time.monotonic()
        ctx = RunContext(
            run_id=run_id,
            workflow=wf,
            trigger_type=trigger_type,
            trigger=payload if payload is not None else {},
            started_at=started_at,
        )
        ctx.state = await asyncio.to_thread(self.store.get_state, wf.name)
        log = RunLogger(self.store, self.bus, run_id, wf.name)
        self.bus.publish(
            {
                "type": "run.started",
                "run_id": run_id,
                "workflow": wf.name,
                "trigger_type": trigger_type,
                "started_at": started_at,
            }
        )
        log.info(f"run started (trigger: {trigger_type})")

        status, error = "success", None
        cancelled = False
        try:
            ctx.vars = templating.render(wf.vars, ctx.template_context())
            body = self._run_steps(ctx, log, wf.steps)
            if wf.timeout:
                await asyncio.wait_for(body, wf.timeout)
            else:
                await body
        except StopRun as stop:
            log.info(f"run stopped early: {stop.reason}")
        except StepFailure as failure:
            status, error = "failed", str(failure)
        except asyncio.TimeoutError:
            status, error = "failed", f"workflow timed out after {wf.timeout}s"
        except asyncio.CancelledError:
            status, error, cancelled = "cancelled", "run cancelled", True
        except Exception as exc:
            logger.exception("unexpected engine error in %s", wf.name)
            status, error = "failed", f"{type(exc).__name__}: {exc}"

        if status == "failed":
            log.error(error or "run failed")
            if wf.on_failure:
                ctx.error = error
                log.info("running on_failure steps")
                try:
                    await self._run_steps(ctx, log, wf.on_failure)
                except (StepFailure, StopRun) as exc:
                    log.error(f"on_failure handler did not complete: {exc}")
                except Exception as exc:  # pragma: no cover - defensive
                    log.error(f"on_failure handler crashed: {exc}")

        duration_ms = int((time.monotonic() - t0) * 1000)
        finished_at = utcnow()
        log.info(f"run {status} in {duration_ms} ms")
        await asyncio.to_thread(
            self.store.finish_run, run_id, status, finished_at, duration_ms, error
        )
        self.bus.publish(
            {
                "type": "run.finished",
                "run_id": run_id,
                "workflow": wf.name,
                "status": status,
                "error": error,
                "duration_ms": duration_ms,
                "finished_at": finished_at,
            }
        )
        result = RunResult(run_id, wf.name, status, duration_ms, error, ctx.steps)
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _run_steps(self, ctx: RunContext, log: RunLogger, steps: list[StepSpec]) -> None:
        for spec in steps:
            await self._execute_step(ctx, log, spec)

    # --------------------------------------------------------------- steps

    async def _execute_step(self, ctx: RunContext, log: RunLogger, spec: StepSpec) -> None:
        step_log = log.bind(spec.id)
        started_at = utcnow()
        t0 = time.monotonic()
        row_id = await asyncio.to_thread(
            self.store.start_step, ctx.run_id, spec.id, spec.type, started_at
        )
        self.bus.publish(
            {
                "type": "step.started",
                "run_id": ctx.run_id,
                "workflow": ctx.workflow.name,
                "step_id": spec.id,
                "step_type": spec.type,
            }
        )

        record: dict[str, Any]
        attempts = 0
        stop: StopRun | None = None
        try:
            if spec.for_each is None:
                if spec.if_ is not None and not templating.truthy(spec.if_, ctx.template_context()):
                    record = {"status": "skipped", "output": None, "error": None}
                    step_log.info("skipped (condition is false)")
                else:
                    output, attempts, err = await self._attempt(ctx, log, step_log, spec, {})
                    record = {
                        "status": "failed" if err else "success",
                        "output": output,
                        "error": err,
                    }
            else:
                record, attempts = await self._loop(ctx, log, step_log, spec)
        except StopRun as exc:
            stop = exc
            record = {
                "status": "success",
                "output": {"stopped": True, "reason": exc.reason},
                "error": None,
            }
        except StepConfigError as exc:
            record = {"status": "failed", "output": None, "error": str(exc)}
            step_log.error(str(exc))

        ctx.steps[spec.id] = record
        duration_ms = int((time.monotonic() - t0) * 1000)
        await asyncio.to_thread(
            self.store.finish_step,
            row_id,
            record["status"],
            attempts,
            utcnow(),
            duration_ms,
            record.get("output"),
            record.get("error"),
        )
        self.bus.publish(
            {
                "type": "step.finished",
                "run_id": ctx.run_id,
                "workflow": ctx.workflow.name,
                "step_id": spec.id,
                "status": record["status"],
                "duration_ms": duration_ms,
                "error": record.get("error"),
            }
        )
        if stop is not None:
            raise stop
        if record["status"] == "failed":
            if spec.continue_on_error:
                step_log.warning("step failed; continuing because continue_on_error is set")
            else:
                raise StepFailure(spec.id, record.get("error") or "unknown error")

    async def _loop(
        self, ctx: RunContext, log: RunLogger, step_log: RunLogger, spec: StepSpec
    ) -> tuple[dict[str, Any], int]:
        raw = spec.for_each
        items = templating.render(raw, ctx.template_context()) if isinstance(raw, str) else raw
        if items is None:
            items = []
        elif isinstance(items, dict):
            items = [{"key": k, "value": v} for k, v in items.items()]
        elif not isinstance(items, (list, tuple)):
            raise StepConfigError(f"for_each must evaluate to a list, got {type(items).__name__}")
        total = len(items)
        results: list[dict[str, Any]] = []
        attempts = 0
        for index, item in enumerate(items):
            extra = {
                "item": item,
                "loop": {
                    "index": index + 1,
                    "index0": index,
                    "first": index == 0,
                    "last": index == total - 1,
                    "length": total,
                },
            }
            if spec.if_ is not None and not templating.truthy(
                spec.if_, ctx.template_context(extra)
            ):
                continue
            output, used, err = await self._attempt(ctx, log, step_log, spec, extra)
            attempts += used
            results.append({"item": item, "ok": err is None, "output": output, "error": err})
            if err and not spec.continue_on_error:
                break
        failures = [r for r in results if not r["ok"]]
        if failures:
            status = "failed"
        elif not results and total:
            status = "skipped"
        else:
            status = "success"
        step_log.info(
            f"loop finished: {len(results)}/{total} item(s) processed, {len(failures)} failed"
        )
        record = {
            "status": status,
            "output": [r["output"] for r in results],
            "results": results,
            "error": failures[0]["error"] if failures else None,
        }
        return record, attempts

    async def _attempt(
        self,
        ctx: RunContext,
        log: RunLogger,
        step_log: RunLogger,
        spec: StepSpec,
        extra: dict[str, Any],
    ) -> tuple[Any, int, str | None]:
        """Run one step (or loop item) with retries. Returns ``(output, attempts, error)``."""
        policy = spec.retry or RetryPolicy()
        attempt = 0
        error: str | None = None
        while attempt < policy.attempts:
            attempt += 1
            sctx = StepContext(
                run=ctx,
                step=spec,
                log=step_log,
                settings=self.settings,
                http=self.http,
                store=self.store,
                attempt=attempt,
                extra=extra,
                _run_steps=partial(self._run_steps, ctx, log),
            )
            retryable = True
            try:
                if spec.type in RAW_PARAM_STEPS:
                    params = dict(spec.with_)
                else:
                    params = templating.render(spec.with_, ctx.template_context(extra))
                coro = self.registry.call(spec.type, sctx, params)
                output = await (asyncio.wait_for(coro, spec.timeout) if spec.timeout else coro)
                return output, attempt, None
            except StopRun:
                raise
            except asyncio.TimeoutError:
                error = f"timed out after {spec.timeout}s"
            except StepFailure as exc:
                error, retryable = str(exc), False
            except StepConfigError as exc:
                error, retryable = str(exc), False
            except StepError as exc:
                error, retryable = str(exc), exc.retryable
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__

            if not retryable or attempt >= policy.attempts:
                step_log.error(
                    f"failed after {attempt} attempt(s): {error}"
                    if attempt > 1
                    else f"failed: {error}"
                )
                break
            delay = policy.delay_for(attempt)
            step_log.warning(
                f"attempt {attempt}/{policy.attempts} failed: {error} — retrying in {delay:.1f}s"
            )
            await self._sleep(delay)
        return None, attempt, error
