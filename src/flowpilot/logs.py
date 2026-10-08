"""Structured logging setup (human-friendly text or one-JSON-object-per-line)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Format records as single-line JSON, including any ``extra=`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Compact text format that appends ``key=value`` extras."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v
            for k, v in vars(record).items()
            if k not in _RESERVED and not k.startswith("_") and v is not None
        }
        if extras:
            base += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return base


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Configure the ``flowpilot`` logger hierarchy."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger("flowpilot")
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    root.propagate = False
