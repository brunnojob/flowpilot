"""Jinja2-based templating used to render step parameters and conditions.

Rendering rules:

* A string that is *exactly* one ``{{ expression }}`` evaluates to the native
  Python value of the expression (lists stay lists, numbers stay numbers).
* Any other string containing ``{{`` or ``{%`` is rendered as text.
* Dicts and lists are rendered recursively (dict keys included).

The environment is sandboxed (``ImmutableSandboxedEnvironment``) and missing
attributes are forgiving: ``steps.missing.output.x`` renders as an empty
string / ``None`` instead of raising.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import jmespath
from jinja2 import ChainableUndefined, TemplateError, Undefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

from flowpilot.errors import StepConfigError
from flowpilot.jalali import fa_digits, format_jalali

_SINGLE_EXPR = re.compile(r"^\s*\{\{(?P<expr>(?:(?!\}\}).)*)\}\}\s*$", re.DOTALL)
_MD_SPECIAL = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def _jmespath(data: Any, expression: str) -> Any:
    return jmespath.search(expression, _plain(data))


def _tojson(value: Any, indent: int | None = None) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, indent=indent, default=str)


def _fromjson(value: str) -> Any:
    return json.loads(value)


def _number(value: Any, digits: int = 2) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{num:,.{digits}f}"


def _md_escape(value: Any) -> str:
    """Escape text for Telegram ``MarkdownV2``."""
    return _MD_SPECIAL.sub(r"\\\1", str(value))


def _strftime(value: Any, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    return str(value)


def _now(tz: str | None = None) -> datetime:
    return datetime.now(ZoneInfo(tz)) if tz else datetime.now(timezone.utc).astimezone()


def _truncate_text(value: Any, length: int = 200, end: str = "…") -> str:
    text = str(value)
    return text if len(text) <= length else text[: max(length - len(end), 0)] + end


def _plain(value: Any) -> Any:
    """Convert Jinja undefined values to ``None`` recursively."""
    if isinstance(value, Undefined):
        return None
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


class _Env(ImmutableSandboxedEnvironment):
    def __init__(self) -> None:
        super().__init__(
            undefined=ChainableUndefined,
            autoescape=False,
            keep_trailing_newline=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.filters.update(
            jmespath=_jmespath,
            tojson=_tojson,
            fromjson=_fromjson,
            number=_number,
            md_escape=_md_escape,
            strftime=_strftime,
            b64encode=lambda v: base64.b64encode(str(v).encode()).decode(),
            b64decode=lambda v: base64.b64decode(str(v)).decode(),
            sha256=lambda v: hashlib.sha256(str(v).encode()).hexdigest(),
            truncate_text=_truncate_text,
            jalali=format_jalali,
            fa_digits=fa_digits,
        )
        self.globals.update(now=_now, uuid=lambda: uuid.uuid4().hex, jmespath=_jmespath)

    def getattr(self, obj: Any, attribute: str) -> Any:
        # JSON-friendly: for dicts, keys win over methods (``data.items`` is the
        # "items" key, not ``dict.items``).
        if isinstance(obj, dict) and attribute in obj:
            return obj[attribute]
        return super().getattr(obj, attribute)


ENV = _Env()


@lru_cache(maxsize=2048)
def _compile_expr(expr: str) -> Any:
    return ENV.compile_expression(expr, undefined_to_none=True)


@lru_cache(maxsize=2048)
def _compile_template(source: str) -> Any:
    return ENV.from_string(source)


def is_template(value: Any) -> bool:
    """Return True if ``value`` is a string containing template syntax."""
    return isinstance(value, str) and ("{{" in value or "{%" in value)


def evaluate(expression: str, context: dict[str, Any]) -> Any:
    """Evaluate a bare Jinja expression (without ``{{ }}``) to a native value."""
    try:
        return _plain(_compile_expr(expression)(**context))
    except TemplateError as exc:
        raise StepConfigError(f"template error in {expression!r}: {exc}") from exc


def render(value: Any, context: dict[str, Any]) -> Any:
    """Render ``value`` (str, dict, list or scalar) against ``context``."""
    if isinstance(value, str):
        if not is_template(value):
            return value
        match = _SINGLE_EXPR.match(value)
        if match and "{%" not in value:
            return evaluate(match.group("expr"), context)
        try:
            return _compile_template(value).render(**context)
        except TemplateError as exc:
            raise StepConfigError(f"template error: {exc}") from exc
    if isinstance(value, dict):
        return {
            render(k, context) if is_template(k) else k: render(v, context)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [render(v, context) for v in value]
    return value


def truthy(value: Any, context: dict[str, Any]) -> bool:
    """Evaluate a condition: bools as-is, strings rendered then interpreted."""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and not is_template(value):
        result: Any = evaluate(value, context)
    else:
        result = render(value, context)
    if isinstance(result, str):
        return result.strip().lower() not in {"", "false", "0", "no", "none", "null", "off"}
    return bool(result)
