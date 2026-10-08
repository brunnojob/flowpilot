"""``state`` — persist small values between runs of the same workflow.

State is available in templates as ``state.<key>``, which makes "only notify
when something changed" workflows trivial.
"""

from __future__ import annotations

from typing import Any

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError
from flowpilot.registry import step


def _deep_merge(base: Any, update: Any) -> Any:
    if isinstance(base, dict) and isinstance(update, dict):
        out = dict(base)
        for key, value in update.items():
            out[key] = _deep_merge(out.get(key), value)
        return out
    return update


@step("state")
def state(
    ctx: StepContext,
    set: dict[str, Any] | None = None,
    merge: dict[str, Any] | None = None,
    delete: list[str] | None = None,
) -> dict[str, Any]:
    """Set keys (``set``), deep-merge dicts into keys (``merge``) or ``delete`` keys."""
    if not (set or merge or delete):
        raise StepConfigError("state: provide at least one of set, merge or delete")
    changes: dict[str, Any] = dict(set or {})
    for key, value in (merge or {}).items():
        changes[key] = _deep_merge(ctx.run.state.get(key), value)
    if changes:
        ctx.update_state(changes)
    if delete:
        ctx.delete_state(list(delete))
    return {"state": dict(ctx.run.state)}
