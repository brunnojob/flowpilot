"""``transform`` — reshape data with Jinja2 templates or JMESPath."""

from __future__ import annotations

import json as jsonlib
from typing import Any

import jmespath as jmespath_lib
from jmespath.exceptions import JMESPathError

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError
from flowpilot.registry import step
from flowpilot.templating import _plain


@step("transform")
def transform(
    ctx: StepContext,
    value: Any = None,
    data: Any = None,
    jmespath: str | None = None,
    template: str | None = None,
    parse_json: bool = False,
) -> Any:
    """Produce a new value from templates or JMESPath.

    * ``value`` — any (templated) structure, returned as-is after rendering.
    * ``template`` — a Jinja2 text template, returned as a string.
    * ``jmespath`` — a JMESPath expression applied to ``data`` (or ``value``).
    * ``parse_json`` — parse the resulting string as JSON.
    """
    result: Any
    if jmespath is not None:
        source = data if data is not None else value
        try:
            result = jmespath_lib.search(jmespath, _plain(source))
        except JMESPathError as exc:
            raise StepConfigError(f"transform: invalid JMESPath {jmespath!r}: {exc}") from exc
    elif template is not None:
        result = template
    else:
        result = value if value is not None else data
    if parse_json:
        if not isinstance(result, str):
            raise StepConfigError("transform: parse_json requires a string result")
        try:
            result = jsonlib.loads(result)
        except ValueError as exc:
            raise StepConfigError(f"transform: invalid JSON: {exc}") from exc
    return result
