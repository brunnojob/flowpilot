"""FastAPI application factory.

Routes:

* ``GET /`` — the dashboard (static HTML/CSS/JS, no build step)
* ``/api/*`` — REST API (optionally protected by ``FLOWPILOT_API_TOKEN``)
* ``/api/events`` and ``/api/runs/{id}/stream`` — Server-Sent Events
* ``/hooks/{path}`` — webhook triggers
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from flowpilot import __version__, templating
from flowpilot.errors import WorkflowNotFound
from flowpilot.models import WebhookTrigger, WorkflowSpec
from flowpilot.project import Project
from flowpilot.triggers import TriggerManager

logger = logging.getLogger("flowpilot.server")

STATIC_DIR = Path(str(files("flowpilot.server") / "static"))
PING_SECONDS = 15.0


class RunRequest(BaseModel):
    """Body of ``POST /api/workflows/{name}/run``."""

    payload: dict[str, Any] | None = None
    wait: bool = False


def _describe_trigger(wf: WorkflowSpec) -> str:
    t = wf.trigger
    if t.type == "cron":
        return f"cron {t.cron}" + (f" ({t.timezone})" if t.timezone else "")
    if t.type == "interval":
        secs = t.seconds
        return f"every {int(secs // 60)}m" if secs >= 60 and secs % 60 == 0 else f"every {secs:g}s"
    if t.type == "webhook":
        return f"{'/'.join(t.methods)} /hooks/{wf.webhook_path}"
    if t.type == "file":
        return f"files in {t.path}"
    if t.type == "feed":
        return f"feed {t.url}"
    return "manual"


def create_app(project: Project, *, start_triggers: bool = True) -> FastAPI:
    """Build the FastAPI app for ``project``."""
    engine = project.engine
    settings = project.settings
    manager = TriggerManager(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await engine.start()
        if start_triggers:
            await manager.start()
        logger.info("flowpilot %s ready with %d workflow(s)", __version__, len(engine.workflows))
        try:
            yield
        finally:
            await manager.stop()
            await engine.close()

    app = FastAPI(
        title="flowpilot",
        version=__version__,
        description="Lightweight self-hosted workflow automation engine.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.project = project
    app.state.triggers = manager

    # ----------------------------------------------------------------- auth

    def require_token(request: Request) -> None:
        token = settings.api_token
        if not token:
            return
        supplied: str | None = request.headers.get("x-flowpilot-token") or request.query_params.get(
            "token"
        )
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if not supplied or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="invalid or missing API token")

    guarded = [Depends(require_token)]

    # -------------------------------------------------------------- helpers

    def get_wf(name: str) -> WorkflowSpec:
        try:
            return engine.get(name)
        except WorkflowNotFound:
            raise HTTPException(404, f"workflow {name!r} not found") from None

    def workflow_info(
        wf: WorkflowSpec, summaries: dict[str, Any], overrides: dict[str, bool]
    ) -> dict[str, Any]:
        trigger = wf.trigger.model_dump()
        if trigger.get("secret"):
            trigger["secret"] = "***"
        summary = summaries.get(wf.name, {})
        nxt = manager.next_fire(wf.name)
        source = Path(wf.source) if wf.source else None
        try:
            rel = str(source.relative_to(settings.project_dir)) if source else None
        except ValueError:
            rel = str(source)
        return {
            "name": wf.name,
            "description": wf.description,
            "enabled": overrides.get(wf.name, wf.enabled),
            "trigger": trigger,
            "trigger_type": wf.trigger.type,
            "trigger_label": _describe_trigger(wf),
            "webhook_path": f"/hooks/{wf.webhook_path}" if wf.webhook_path else None,
            "steps": [{"id": s.id, "type": s.type, "name": s.label} for s in wf.steps],
            "on_failure": [{"id": s.id, "type": s.type} for s in wf.on_failure],
            "tags": wf.tags,
            "source": rel,
            "next_run": nxt.isoformat() if nxt else None,
            "trigger_active": manager.is_active(wf.name),
            "last_run": summary.get("last_run"),
            "recent": summary.get("recent", []),
        }

    # ------------------------------------------------------------ dashboard

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ------------------------------------------------------------------ api

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "workflows": len(engine.workflows)}

    @app.get("/api/info", tags=["system"], dependencies=guarded)
    async def info() -> dict[str, Any]:
        return {
            "version": __version__,
            "project_dir": str(settings.project_dir),
            "workflows_dir": str(settings.workflows_dir),
            "allow_shell": settings.allow_shell,
            "auth": bool(settings.api_token),
            "active_runs": engine.active_runs,
            "load_errors": project.load_result.errors,
        }

    @app.get("/api/stats", tags=["system"], dependencies=guarded)
    async def stats(hours: int = Query(24, ge=1, le=24 * 365)) -> dict[str, Any]:
        data = await asyncio.to_thread(engine.store.stats, hours)
        overrides = engine.store.get_enabled_overrides()
        data["workflows"] = len(engine.workflows)
        data["enabled"] = sum(overrides.get(n, w.enabled) for n, w in engine.workflows.items())
        return data

    @app.get("/api/steps", tags=["system"], dependencies=guarded)
    async def step_types() -> list[dict[str, Any]]:
        return [s.to_dict() for s in engine.registry.all()]

    @app.post("/api/reload", tags=["system"], dependencies=guarded)
    async def reload() -> dict[str, Any]:
        await manager.stop()
        result = project.reload()
        await manager.start()
        return {"workflows": [w.name for w in result.workflows], "errors": result.errors}

    @app.get("/api/workflows", tags=["workflows"], dependencies=guarded)
    async def list_workflows() -> list[dict[str, Any]]:
        summaries = await asyncio.to_thread(engine.store.workflow_summaries)
        overrides = engine.store.get_enabled_overrides()
        return [workflow_info(wf, summaries, overrides) for wf in engine.workflows.values()]

    @app.get("/api/workflows/{name}", tags=["workflows"], dependencies=guarded)
    async def get_workflow(name: str) -> dict[str, Any]:
        wf = get_wf(name)
        summaries = await asyncio.to_thread(engine.store.workflow_summaries)
        data = workflow_info(wf, summaries, engine.store.get_enabled_overrides())
        definition = None
        if wf.source and Path(wf.source).suffix in {".yaml", ".yml", ".py"}:
            try:
                definition = Path(wf.source).read_text(encoding="utf-8")
            except OSError:
                definition = None
        data["definition"] = definition
        data["state"] = {
            k: v for k, v in engine.store.get_state(name).items() if not k.startswith("_")
        }
        return data

    @app.post(
        "/api/workflows/{name}/run", tags=["workflows"], dependencies=guarded, status_code=202
    )
    async def run_workflow(name: str, body: RunRequest | None = None) -> dict[str, Any]:
        get_wf(name)
        body = body or RunRequest()
        run_id = await engine.submit(name, "manual", body.payload or {})
        if body.wait:
            result = await engine.wait(run_id)
            return result.to_dict() if result else {"run_id": run_id}
        return {"run_id": run_id, "status": "running"}

    def _toggle(name: str, enabled: bool) -> dict[str, Any]:
        get_wf(name)
        engine.set_enabled(name, enabled)
        manager.sync(name)
        return {"name": name, "enabled": enabled}

    @app.post("/api/workflows/{name}/enable", tags=["workflows"], dependencies=guarded)
    async def enable(name: str) -> dict[str, Any]:
        return _toggle(name, True)

    @app.post("/api/workflows/{name}/disable", tags=["workflows"], dependencies=guarded)
    async def disable(name: str) -> dict[str, Any]:
        return _toggle(name, False)

    @app.delete("/api/workflows/{name}/state", tags=["workflows"], dependencies=guarded)
    async def reset_state(name: str) -> dict[str, Any]:
        get_wf(name)
        engine.store.delete_state(name)
        return {"name": name, "state": {}}

    @app.get("/api/runs", tags=["runs"], dependencies=guarded)
    async def list_runs(
        workflow: str | None = None,
        status: str | None = None,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        runs = await asyncio.to_thread(engine.store.list_runs, workflow, status, limit, offset)
        total = await asyncio.to_thread(engine.store.count_runs, workflow, status)
        return {"runs": runs, "total": total, "limit": limit, "offset": offset}

    @app.get("/api/runs/{run_id}", tags=["runs"], dependencies=guarded)
    async def get_run(run_id: str) -> dict[str, Any]:
        run = await asyncio.to_thread(engine.store.get_run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        run["logs"] = await asyncio.to_thread(engine.store.get_logs, run_id)
        return run

    @app.get("/api/runs/{run_id}/logs", tags=["runs"], dependencies=guarded)
    async def get_logs(run_id: str, after: int = 0) -> list[dict[str, Any]]:
        if engine.store.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return await asyncio.to_thread(engine.store.get_logs, run_id, after)

    # ------------------------------------------------------------------ SSE

    def _sse(event: str, data: Any) -> str:
        return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"

    async def _stream(
        request: Request,
        replay: Callable[[], list[str]] | None,
        accept: Callable[[dict[str, Any]], bool],
        done: Callable[[dict[str, Any]], bool] | None = None,
        finished_already: Callable[[], bool] | None = None,
    ) -> AsyncIterator[str]:
        async with engine.bus.subscribe() as queue:
            yield "retry: 3000\n\n"
            if replay:
                for chunk in replay():
                    yield chunk
            if finished_already and finished_already():
                yield _sse("end", {})
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), PING_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if accept(event):
                    yield _sse(event["type"], event)
                    if done and done(event):
                        yield _sse("end", {})
                        return

    sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    @app.get("/api/events", tags=["runs"], dependencies=guarded)
    async def events(request: Request) -> StreamingResponse:
        """Global live event stream (run/step lifecycle; logs excluded)."""
        return StreamingResponse(
            _stream(request, None, lambda e: e["type"] != "log"),
            media_type="text/event-stream",
            headers=sse_headers,
        )

    @app.get("/api/runs/{run_id}/stream", tags=["runs"], dependencies=guarded)
    async def run_stream(run_id: str, request: Request) -> StreamingResponse:
        """Live logs and step updates of one run. Replays existing logs first."""
        if engine.store.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        seen: set[int] = set()

        def replay() -> list[str]:
            out = []
            for log in engine.store.get_logs(run_id):
                seen.add(log["id"])
                out.append(_sse("log", {"type": "log", "run_id": run_id, "log": log}))
            return out

        def finished() -> bool:
            run = engine.store.get_run(run_id)
            return bool(run and run["status"] != "running")

        def accept(e: dict[str, Any]) -> bool:
            if e.get("run_id") != run_id:
                return False
            return not (e["type"] == "log" and e["log"]["id"] in seen)

        return StreamingResponse(
            _stream(request, replay, accept, lambda e: e["type"] == "run.finished", finished),
            media_type="text/event-stream",
            headers=sse_headers,
        )

    # ------------------------------------------------------------- webhooks

    async def webhook(path: str, request: Request) -> JSONResponse:
        """Trigger the workflow whose webhook path matches."""
        wf = engine.find_webhook(path)
        if wf is None or not isinstance(wf.trigger, WebhookTrigger):
            raise HTTPException(404, "no webhook registered at this path")
        trig = wf.trigger
        if request.method not in trig.methods:
            raise HTTPException(405, f"method {request.method} not allowed")
        if not engine.is_enabled(wf.name):
            raise HTTPException(409, f"workflow {wf.name!r} is disabled")
        raw = await request.body()
        if trig.secret:
            secret = str(templating.render(trig.secret, {"env": _environ()}) or "")
            if not secret:
                raise HTTPException(401, "webhook secret is configured but empty")
            if not _verify_secret(secret, request, raw):
                raise HTTPException(401, "invalid webhook secret")
        body: Any
        ctype = request.headers.get("content-type", "")
        if "json" in ctype:
            try:
                body = json.loads(raw or b"null")
            except ValueError:
                raise HTTPException(400, "invalid JSON body") from None
        elif "form" in ctype:
            form = await request.form()
            body = {k: v for k, v in form.items() if isinstance(v, str)}
        else:
            body = raw.decode(errors="replace") if raw else None
        payload = {
            "method": request.method,
            "path": path,
            "query": dict(request.query_params),
            "headers": {k: v for k, v in request.headers.items() if k.lower() != "authorization"},
            "body": body,
            "client": request.client.host if request.client else None,
        }
        run_id = await engine.submit(wf.name, "webhook", payload)
        if trig.wait:
            result = await engine.wait(run_id)
            data: dict[str, Any] = result.to_dict() if result else {"run_id": run_id}
            last = list(result.steps.values())[-1] if result and result.steps else None
            data["output"] = last.get("output") if last else None
            return JSONResponse(data, status_code=200 if result and result.ok else 500)
        return JSONResponse({"run_id": run_id, "status": "accepted"}, status_code=202)

    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        app.add_api_route(
            "/hooks/{path:path}",
            webhook,
            methods=[method],
            tags=["webhooks"],
            operation_id=f"webhook_{method.lower()}",
            response_model=None,
        )

    return app


def _environ() -> dict[str, str]:
    import os

    return dict(os.environ)


def _verify_secret(secret: str, request: Request, raw: bytes) -> bool:
    """Accept ``X-Flowpilot-Secret``, ``?secret=`` or a GitHub ``X-Hub-Signature-256``."""
    supplied: str | None = request.headers.get("x-flowpilot-secret") or request.query_params.get(
        "secret"
    )
    if supplied and hmac.compare_digest(supplied, secret):
        return True
    signature = request.headers.get("x-hub-signature-256", "")
    if signature.startswith("sha256="):
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature[7:], expected)
    return False
