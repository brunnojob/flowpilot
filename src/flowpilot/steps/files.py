"""``file.write`` and ``file.read`` — work with files relative to the project directory."""

from __future__ import annotations

import json
from typing import Any

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError
from flowpilot.registry import step


@step("file.write")
def file_write(
    ctx: StepContext,
    path: str,
    content: Any,
    mode: str = "overwrite",
    encoding: str = "utf-8",
    mkdir: bool = True,
    newline: bool = False,
) -> dict[str, Any]:
    """Write (``overwrite``) or append (``append``) text to a file.

    Non-string content is serialized as JSON. With ``newline: true`` a trailing
    newline is added (handy for JSON-lines logs).
    """
    if mode not in {"overwrite", "append"}:
        raise StepConfigError("file.write: mode must be 'overwrite' or 'append'")
    target = ctx.resolve_path(path)
    if mkdir:
        target.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    if newline and not text.endswith("\n"):
        text += "\n"
    with target.open("a" if mode == "append" else "w", encoding=encoding) as fh:
        fh.write(text)
    ctx.log.info(f"wrote {len(text)} chars to {target}")
    return {"path": str(target), "bytes": target.stat().st_size}


@step("file.read")
def file_read(
    ctx: StepContext, path: str, encoding: str = "utf-8", parse: str | None = None
) -> Any:
    """Read a text file. ``parse`` may be ``json`` or ``lines``."""
    target = ctx.resolve_path(path)
    if not target.is_file():
        raise StepConfigError(f"file.read: {target} does not exist")
    text = target.read_text(encoding=encoding)
    if parse == "json":
        return json.loads(text)
    if parse == "lines":
        return text.splitlines()
    if parse is not None:
        raise StepConfigError("file.read: parse must be 'json' or 'lines'")
    return text
