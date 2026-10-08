"""Exception hierarchy used across flowpilot."""

from __future__ import annotations


class FlowpilotError(Exception):
    """Base class for all flowpilot errors."""


class WorkflowValidationError(FlowpilotError):
    """Raised when a workflow definition is invalid.

    ``errors`` holds human-readable messages, one per problem found.
    """

    def __init__(self, source: str, errors: list[str]) -> None:
        self.source = source
        self.errors = errors
        joined = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"Invalid workflow {source}:\n{joined}")


class StepError(FlowpilotError):
    """Raised by a step handler to signal a (possibly retryable) failure."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class StepConfigError(StepError):
    """A step received invalid parameters. Never retried."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class StopRun(FlowpilotError):
    """Raised (e.g. by the ``condition`` step) to end a run early and successfully."""

    def __init__(self, reason: str = "stopped") -> None:
        super().__init__(reason)
        self.reason = reason


class WorkflowNotFound(FlowpilotError):
    """Raised when a workflow name does not exist in the loaded project."""
