"""In-process publish/subscribe bus that powers the dashboard's live updates (SSE)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    """Fan-out bus: every subscriber gets its own bounded queue.

    Slow subscribers never block the engine: when a queue is full the event is
    dropped for that subscriber only.
    """

    def __init__(self, max_queue: int = 1000) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._max_queue = max_queue
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the loop so events can be published from worker threads."""
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: dict[str, Any]) -> None:
        """Publish an event. Safe to call from any thread."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            if not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._fanout, event)
            return
        self._fanout(event)

    def _fanout(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """Async context manager yielding a queue of events."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._max_queue)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
