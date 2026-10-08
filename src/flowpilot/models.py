"""Pydantic models describing workflows, triggers and steps.

These models are the single source of truth for the YAML format: the loader
parses YAML into them, ``flowpilot validate`` reports their errors, and the
engine executes them.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

FileEvent = Literal["created", "modified", "deleted"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --------------------------------------------------------------------------- triggers


class ManualTrigger(_Model):
    """Only runs when triggered from the CLI, the REST API or the dashboard."""

    type: Literal["manual"] = "manual"


class CronTrigger(_Model):
    """Runs on a cron schedule (5 fields, optionally a 6th for seconds)."""

    type: Literal["cron"] = "cron"
    cron: str
    timezone: str | None = None

    @field_validator("cron")
    @classmethod
    def _check_cron(cls, value: str) -> str:
        if not croniter.is_valid(value):
            raise ValueError(f"invalid cron expression: {value!r}")
        return value

    @field_validator("timezone")
    @classmethod
    def _check_tz(cls, value: str | None) -> str | None:
        if value is None:
            return value
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"unknown timezone: {value!r}") from exc
        return value


class IntervalTrigger(_Model):
    """Runs every ``seconds`` seconds."""

    type: Literal["interval"] = "interval"
    seconds: float = Field(ge=1)
    run_on_start: bool = False


class WebhookTrigger(_Model):
    """Runs when an HTTP request hits ``/hooks/<path>``."""

    type: Literal["webhook"] = "webhook"
    path: str | None = None
    methods: list[str] = Field(default_factory=lambda: ["POST"])
    secret: str | None = None
    wait: bool = False

    @field_validator("methods")
    @classmethod
    def _upper(cls, value: list[str]) -> list[str]:
        allowed = {"GET", "POST", "PUT", "PATCH", "DELETE"}
        out = [m.upper() for m in value]
        bad = [m for m in out if m not in allowed]
        if bad:
            raise ValueError(f"unsupported HTTP methods: {bad}")
        return out

    @field_validator("path")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip("/") if value else value


def _default_file_events() -> list[FileEvent]:
    return ["created", "modified"]


class FileTrigger(_Model):
    """Runs when files under ``path`` are created, modified or deleted (polling based)."""

    type: Literal["file"] = "file"
    path: str
    patterns: list[str] = Field(default_factory=lambda: ["*"])
    events: list[FileEvent] = Field(default_factory=lambda: _default_file_events())
    interval: float = Field(2.0, ge=0.1)
    recursive: bool = True


class FeedTrigger(_Model):
    """Runs once per new entry of an RSS/Atom feed."""

    type: Literal["feed"] = "feed"
    url: str
    interval: float = Field(300.0, ge=5)
    initial: Literal["skip", "fire"] = "skip"
    max_items: int = Field(10, ge=1, le=200)


TriggerSpec = Annotated[
    ManualTrigger | CronTrigger | IntervalTrigger | WebhookTrigger | FileTrigger | FeedTrigger,
    Field(discriminator="type"),
]

# ----------------------------------------------------------------------------- steps


class RetryPolicy(_Model):
    """Exponential backoff retry policy.

    The delay before retry *n* (1-based) is ``min(delay * backoff ** (n - 1), max_delay)``.
    """

    attempts: int = Field(1, ge=1, le=100)
    delay: float = Field(1.0, ge=0)
    backoff: float = Field(2.0, ge=1)
    max_delay: float = Field(300.0, ge=0)

    def delay_for(self, retry_number: int) -> float:
        """Seconds to wait before the given retry (1 = first retry)."""
        return min(self.delay * self.backoff ** max(retry_number - 1, 0), self.max_delay)


class StepSpec(_Model):
    """One step of a workflow."""

    id: str
    type: str
    name: str | None = None
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")
    if_: str | bool | None = Field(None, alias="if")
    for_each: str | list[Any] | None = None
    timeout: float | None = Field(None, gt=0)
    retry: RetryPolicy | None = None
    continue_on_error: bool = False

    @model_validator(mode="before")
    @classmethod
    def _shorthands(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("retry"), int):
            data = {**data, "retry": {"attempts": data["retry"]}}
        return data

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _IDENT_RE.match(value):
            raise ValueError(
                f"step id {value!r} must be a valid identifier (letters, digits, underscore)"
            )
        return value

    @property
    def label(self) -> str:
        return self.name or self.id


class WorkflowSpec(_Model):
    """A complete workflow: a trigger plus an ordered list of steps."""

    name: str
    description: str = ""
    enabled: bool = True
    trigger: TriggerSpec = Field(default_factory=ManualTrigger)
    vars: dict[str, Any] = Field(default_factory=dict)
    steps: list[StepSpec] = Field(min_length=1)
    on_failure: list[StepSpec] = Field(default_factory=list)
    timeout: float | None = Field(None, gt=0)
    concurrency: int = Field(1, ge=1, le=100)
    tags: list[str] = Field(default_factory=list)
    source: str | None = Field(None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        trig = data.get("trigger")
        if isinstance(trig, str):
            data["trigger"] = {"type": trig}
        for key in ("steps", "on_failure"):
            steps = data.get(key)
            if isinstance(steps, list):
                data[key] = _autoname(steps, prefix="step" if key == "steps" else "on_failure")
        return data

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(
                f"workflow name {value!r} may only contain letters, digits, '.', '_' and '-'"
            )
        return value

    @model_validator(mode="after")
    def _unique_ids(self) -> WorkflowSpec:
        seen: set[str] = set()
        for spec in iter_steps(self.steps) + iter_steps(self.on_failure):
            if spec.id in seen:
                raise ValueError(f"duplicate step id {spec.id!r}")
            seen.add(spec.id)
        return self

    @property
    def webhook_path(self) -> str | None:
        """The URL path (below ``/hooks/``) for webhook-triggered workflows."""
        if isinstance(self.trigger, WebhookTrigger):
            return self.trigger.path or self.name
        return None


def _autoname(steps: list[Any], prefix: str) -> list[Any]:
    out: list[Any] = []
    for index, raw in enumerate(steps, start=1):
        if isinstance(raw, dict) and "id" not in raw:
            raw = {**raw, "id": f"{prefix}_{index}"}
        out.append(raw)
    return out


def branch_cases(spec: StepSpec) -> list[tuple[str | bool | None, list[StepSpec]]]:
    """Parse nested steps of a ``branch`` step into ``(condition, steps)`` pairs.

    The default branch is returned last with condition ``None``.
    """
    cases: list[tuple[str | bool | None, list[StepSpec]]] = []
    for i, case in enumerate(spec.with_.get("cases") or [], start=1):
        if not isinstance(case, dict) or "when" not in case:
            raise ValueError(f"branch {spec.id!r}: case #{i} needs a 'when' expression")
        steps = _autoname(case.get("steps") or [], prefix=f"{spec.id}_case{i}")
        cases.append((case["when"], [StepSpec.model_validate(s) for s in steps]))
    default = _autoname(spec.with_.get("default") or [], prefix=f"{spec.id}_default")
    if default:
        cases.append((None, [StepSpec.model_validate(s) for s in default]))
    return cases


def iter_steps(steps: list[StepSpec]) -> list[StepSpec]:
    """Flatten steps, including those nested inside ``branch`` steps."""
    out: list[StepSpec] = []
    for spec in steps:
        out.append(spec)
        if spec.type == "branch":
            for _, nested in branch_cases(spec):
                out.extend(iter_steps(nested))
    return out


def define(
    name: str,
    steps: list[dict[str, Any] | StepSpec],
    *,
    trigger: dict[str, Any] | str = "manual",
    **kwargs: Any,
) -> WorkflowSpec:
    """Define a workflow from Python code.

    Example::

        workflow = define(
            "hello",
            trigger={"type": "cron", "cron": "0 9 * * *"},
            steps=[{"id": "greet", "type": "log", "with": {"message": "hi"}}],
        )
    """
    raw_steps = [s.model_dump(by_alias=True) if isinstance(s, StepSpec) else s for s in steps]
    return WorkflowSpec.model_validate(
        {"name": name, "trigger": trigger, "steps": raw_steps, **kwargs}
    )
