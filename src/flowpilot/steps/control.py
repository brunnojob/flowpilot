"""Control-flow steps: ``condition``, ``branch``, ``delay`` and ``log``."""

from __future__ import annotations

import asyncio
from typing import Any

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError, StopRun
from flowpilot.models import branch_cases
from flowpilot.registry import step


@step("condition")
async def condition(ctx: StepContext, check: Any, reason: str | None = None) -> dict[str, Any]:
    """Gate: continue the run only if ``check`` is truthy, otherwise stop successfully.

    ``check`` accepts the same forms as ``if:`` — a bool, a bare expression
    (``trigger.count > 3``) or a ``{{ template }}``.
    """
    passed = ctx.evaluate(check)
    if not passed:
        raise StopRun(str(ctx.render(reason)) if reason else "condition not met")
    return {"passed": True}


@step("branch")
async def branch(
    ctx: StepContext,
    cases: list[dict[str, Any]] | None = None,
    default: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the steps of the first case whose ``when`` is truthy (or ``default``)."""
    try:
        parsed = branch_cases(ctx.step)
    except ValueError as exc:
        raise StepConfigError(str(exc)) from exc
    for index, (when, steps) in enumerate(parsed, start=1):
        if when is None or ctx.evaluate(when):
            label = "default" if when is None else f"case {index}"
            ctx.log.info(f"taking {label} ({len(steps)} step(s))")
            await ctx.run_steps(steps)
            return {"taken": label, "index": None if when is None else index}
    ctx.log.info("no branch matched")
    return {"taken": None, "index": None}


@step("delay")
async def delay(ctx: StepContext, seconds: float) -> dict[str, float]:
    """Pause the run for ``seconds`` seconds."""
    if seconds < 0:
        raise StepConfigError("delay: seconds must be >= 0")
    await asyncio.sleep(float(seconds))
    return {"slept": float(seconds)}


@step("log")
async def log(ctx: StepContext, message: Any, level: str = "info") -> dict[str, Any]:
    """Write a message to the run log."""
    level = level.lower()
    if level not in {"debug", "info", "warning", "error"}:
        raise StepConfigError(f"log: unknown level {level!r}")
    ctx.log.log(level, str(message))
    return {"message": str(message)}
