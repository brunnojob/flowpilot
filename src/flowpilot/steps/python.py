"""``python`` — call any importable Python function."""

from __future__ import annotations

import importlib
import inspect
import sys
from typing import Any

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError
from flowpilot.registry import step


def load_callable(ref: str, project_dir: str | None = None) -> Any:
    """Import ``"package.module:attr"`` (or ``"package.module.attr"``)."""
    if project_dir and project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    module_name, sep, attr = ref.partition(":")
    if not sep:
        module_name, _, attr = ref.rpartition(".")
    if not module_name or not attr:
        raise StepConfigError(f"python: function must look like 'module:function' (got {ref!r})")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise StepConfigError(f"python: cannot import {module_name!r}: {exc}") from exc
    obj: Any = module
    for part in attr.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError:
            raise StepConfigError(f"python: {module_name!r} has no attribute {attr!r}") from None
    if not callable(obj):
        raise StepConfigError(f"python: {ref!r} is not callable")
    return obj


@step("python")
async def python_call(ctx: StepContext, function: str, args: dict[str, Any] | None = None) -> Any:
    """Call ``function`` (``module:func``) with ``args`` as keyword arguments.

    If the function declares a ``ctx`` parameter it receives the step context.
    Async functions are awaited; sync functions run in a worker thread.
    """
    import asyncio

    func = load_callable(function, str(ctx.project_dir))
    kwargs = dict(args or {})
    try:
        if "ctx" in inspect.signature(func).parameters:
            kwargs["ctx"] = ctx
    except (TypeError, ValueError):  # pragma: no cover - builtins without signature
        pass
    if inspect.iscoroutinefunction(func):
        return await func(**kwargs)
    result = await asyncio.to_thread(func, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result
