"""Step registry and the ``@step`` decorator used by built-in and plugin steps.

A step handler is a plain (sync or async) function whose first parameter is
the :class:`~flowpilot.context.StepContext` and whose remaining keyword
parameters are filled from the step's ``with:`` mapping::

    from flowpilot import step

    @step("greet", description="Return a greeting")
    async def greet(ctx, name: str, punctuation: str = "!") -> str:
        ctx.log.info(f"greeting {name}")
        return f"Hello, {name}{punctuation}"

Sync handlers run in a worker thread so they never block the event loop.
Third-party packages can expose steps through the ``flowpilot.steps`` entry
point group; the entry point may reference a module (imported for its
decorators) or a ``StepRegistry``-aware callable ``register(registry)``.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from flowpilot.errors import StepConfigError

logger = logging.getLogger("flowpilot.registry")

ENTRY_POINT_GROUP = "flowpilot.steps"

Handler = Callable[..., Any]


@dataclass
class StepType:
    """Metadata about a registered step type."""

    name: str
    func: Handler
    description: str = ""
    source: str = "builtin"
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    accepts_any: bool = False

    @property
    def is_async(self) -> bool:
        return inspect.iscoroutinefunction(self.func)

    def check_params(self, params: dict[str, Any]) -> list[str]:
        """Return a list of problems with ``params`` (unknown or missing keys)."""
        problems: list[str] = []
        if not self.accepts_any:
            unknown = sorted(set(params) - set(self.params))
            if unknown:
                known = ", ".join(sorted(self.params)) or "none"
                problems.append(
                    f"unknown parameter(s) for step type '{self.name}': {', '.join(unknown)}"
                    f" (known: {known})"
                )
        missing = sorted(k for k, p in self.params.items() if p["required"] and k not in params)
        if missing:
            problems.append(
                f"missing required parameter(s) for '{self.name}': {', '.join(missing)}"
            )
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "params": self.params,
        }


def _introspect(func: Handler) -> tuple[dict[str, dict[str, Any]], bool]:
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    if not params:
        raise TypeError(f"step handler {func!r} must accept the step context as first argument")
    out: dict[str, dict[str, Any]] = {}
    accepts_any = False
    for p in params[1:]:
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            accepts_any = True
            continue
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.POSITIONAL_ONLY):
            continue
        required = p.default is inspect.Parameter.empty
        annotation = p.annotation
        if annotation is inspect.Parameter.empty:
            type_name = "any"
        elif isinstance(annotation, str):
            type_name = annotation
        else:
            type_name = getattr(annotation, "__name__", str(annotation))
        out[p.name] = {
            "required": required,
            "default": None if required else _jsonable(p.default),
            "type": type_name,
        }
    return out, accepts_any


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return repr(value)


class StepRegistry:
    """A mapping of step type name to handler.

    A registry may have a ``parent``: names not found locally are looked up
    there. :meth:`clone` uses this so that child registries see every step
    registered on the default registry (built-ins, plugins, ``@step``) while
    their own registrations stay private.
    """

    def __init__(self, parent: StepRegistry | None = None) -> None:
        self._types: dict[str, StepType] = {}
        self._entry_points_loaded = False
        self.parent = parent

    def register(
        self,
        name: str,
        func: Handler,
        *,
        description: str | None = None,
        source: str = "builtin",
        replace: bool = False,
    ) -> StepType:
        """Register ``func`` as step type ``name``."""
        if name in self._types and not replace and self._types[name].func is not func:
            raise ValueError(f"step type {name!r} is already registered")
        params, accepts_any = _introspect(func)
        doc = description or (inspect.getdoc(func) or "").split("\n\n")[0].replace("\n", " ")
        doc = doc.replace("``", "")
        st = StepType(name, func, doc, source, params, accepts_any)
        self._types[name] = st
        return st

    def step(
        self, name: str | None = None, *, description: str | None = None
    ) -> Callable[[Handler], Handler]:
        """Decorator form of :meth:`register`."""

        def decorator(func: Handler) -> Handler:
            module = getattr(func, "__module__", "") or ""
            if module.startswith("flowpilot.steps"):
                source = "builtin"
            elif module.startswith("flowpilot_user_"):
                source = module.removeprefix("flowpilot_user_") + ".py"
            else:
                source = module
            self.register(
                name or func.__name__, func, description=description, source=source, replace=True
            )
            return func

        return decorator

    def clone(self) -> StepRegistry:
        """Return a child registry whose own registrations do not leak into this one."""
        self.ensure_builtins()
        return StepRegistry(parent=self)

    def _all_types(self) -> dict[str, StepType]:
        self.ensure_builtins()
        merged = self.parent._all_types() if self.parent else {}
        merged.update(self._types)
        return merged

    def get(self, name: str) -> StepType:
        types = self._all_types()
        try:
            return types[name]
        except KeyError:
            known = ", ".join(sorted(types))
            raise StepConfigError(f"unknown step type {name!r} (available: {known})") from None

    def __contains__(self, name: object) -> bool:
        return name in self._all_types()

    def all(self) -> list[StepType]:
        return sorted(self._all_types().values(), key=lambda s: s.name)

    def ensure_builtins(self) -> None:
        if self is default_registry:
            importlib.import_module("flowpilot.steps")

    def load_entry_points(self) -> list[str]:
        """Load plugins exposed via the ``flowpilot.steps`` entry point group."""
        if self._entry_points_loaded:
            return []
        self._entry_points_loaded = True
        loaded: list[str] = []
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                obj = ep.load()
                if callable(obj) and not inspect.ismodule(obj):
                    obj(self)
                loaded.append(ep.name)
            except Exception:  # pragma: no cover - depends on installed plugins
                logger.exception("failed to load step plugin %s", ep.name)
        return loaded

    def load_modules(self, modules: list[str]) -> None:
        """Import plugin modules (their ``@step`` decorators register themselves)."""
        for mod in modules:
            importlib.import_module(mod)

    async def call(self, name: str, ctx: Any, params: dict[str, Any]) -> Any:
        """Invoke step type ``name`` with ``params``."""
        st = self.get(name)
        problems = st.check_params(params)
        if problems:
            raise StepConfigError("; ".join(problems))
        if st.is_async:
            return await st.func(ctx, **params)
        result = await asyncio.to_thread(st.func, ctx, **params)
        if inspect.isawaitable(result):
            result = await result
        return result


default_registry = StepRegistry()


def step(
    name: str | None = None, *, description: str | None = None
) -> Callable[[Handler], Handler]:
    """Register a step type in the default registry.

    >>> from flowpilot import step
    >>> @step("double")
    ... def double(ctx, value: int) -> int:
    ...     return value * 2
    """
    return default_registry.step(name, description=description)
