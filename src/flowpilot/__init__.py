"""flowpilot — a lightweight, self-hosted, code-first workflow automation engine.

Public API::

    from flowpilot import step, define, StepContext

    @step("slugify", description="Turn text into a URL-friendly slug")
    def slugify(ctx: StepContext, text: str, sep: str = "-") -> str:
        ...
"""

from __future__ import annotations

__version__ = "0.1.0"

from flowpilot.context import StepContext
from flowpilot.errors import (
    FlowpilotError,
    StepConfigError,
    StepError,
    StopRun,
    WorkflowValidationError,
)
from flowpilot.models import StepSpec, WorkflowSpec, define
from flowpilot.registry import StepRegistry, default_registry, step

__all__ = [
    "FlowpilotError",
    "StepConfigError",
    "StepContext",
    "StepError",
    "StepRegistry",
    "StepSpec",
    "StopRun",
    "WorkflowSpec",
    "WorkflowValidationError",
    "__version__",
    "default_registry",
    "define",
    "step",
]
