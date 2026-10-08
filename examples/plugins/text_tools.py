"""Example plugin: custom steps registered with the ``@step`` decorator.

Enable it by listing ``plugins.text_tools`` under ``plugins:`` in
``flowpilot.yaml``, or ship it in a package and expose it through the
``flowpilot.steps`` entry point group.
"""

from __future__ import annotations

import html
import re
import unicodedata

from flowpilot import StepContext, step

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


@step("html_to_text", description="Strip HTML tags and collapse whitespace")
def html_to_text(ctx: StepContext, html_text: str, max_length: int = 0) -> str:
    text = _WS.sub(" ", html.unescape(_TAG.sub(" ", html_text or ""))).strip()
    if max_length and len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


@step("slugify", description="Turn text into a URL-friendly slug")
def slugify(ctx: StepContext, text: str, separator: str = "-") -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", separator, norm).strip(separator).lower()
