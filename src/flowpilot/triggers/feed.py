"""RSS/Atom feed trigger: one run per new entry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import httpx

from flowpilot.models import FeedTrigger
from flowpilot.triggers.base import TriggerRunner

logger = logging.getLogger("flowpilot.triggers.feed")

SEEN_KEY = "_feed_seen"
MAX_SEEN = 1000


def entry_key(entry: Any) -> str:
    """A stable identity for a feed entry."""
    return str(entry.get("id") or entry.get("link") or entry.get("title") or "")


def entry_payload(entry: Any) -> dict[str, Any]:
    return {
        "id": entry_key(entry),
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "summary": entry.get("summary", ""),
        "author": entry.get("author", ""),
        "published": entry.get("published") or entry.get("updated") or "",
        "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")],
    }


class FeedRunner(TriggerRunner):
    """Polls a feed every ``interval`` seconds and fires for unseen entries."""

    trigger_type = "feed"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        trig = self.workflow.trigger
        assert isinstance(trig, FeedTrigger)
        self.trig = trig

    async def fetch(self) -> Any:
        resp = await self.engine.http.get(self.trig.url, timeout=30)
        resp.raise_for_status()
        return await asyncio.to_thread(feedparser.parse, resp.content)

    async def poll_once(self) -> list[dict[str, Any]]:
        """Fetch the feed and fire runs for new entries (oldest first)."""
        try:
            parsed = await self.fetch()
        except httpx.HTTPError as exc:
            logger.warning("feed fetch failed for %s: %s", self.workflow.name, exc)
            return []
        store = self.engine.store
        state = await asyncio.to_thread(store.get_state, self.workflow.name)
        first_poll = SEEN_KEY not in state
        seen: list[str] = list(state.get(SEEN_KEY, []))
        seen_set = set(seen)
        entries = [e for e in parsed.entries if entry_key(e)][: self.trig.max_items]
        new = [e for e in entries if entry_key(e) not in seen_set]
        fired: list[dict[str, Any]] = []
        if not (first_poll and self.trig.initial == "skip"):
            feed_meta = {
                "title": parsed.feed.get("title", ""),
                "link": parsed.feed.get("link", ""),
            }
            for entry in reversed(new):
                payload = {"entry": entry_payload(entry), "feed": feed_meta}
                await self.fire(payload)
                fired.append(payload)
        seen.extend(entry_key(e) for e in new)
        await asyncio.to_thread(store.set_state, self.workflow.name, {SEEN_KEY: seen[-MAX_SEEN:]})
        return fired

    async def run(self) -> None:
        while True:
            await self.poll_once()
            self.next_fire = datetime.now(timezone.utc) + timedelta(seconds=self.trig.interval)
            await asyncio.sleep(self.trig.interval)
