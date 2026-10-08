"""Polling file watcher trigger (portable: works on any OS and on network mounts)."""

from __future__ import annotations

import asyncio
import fnmatch
from pathlib import Path
from typing import Any

from flowpilot.models import FileTrigger
from flowpilot.triggers.base import TriggerRunner

Snapshot = dict[str, tuple[float, int]]


def snapshot(root: Path, patterns: list[str], recursive: bool = True) -> Snapshot:
    """Map file path → (mtime, size) for files under ``root`` matching ``patterns``."""
    if root.is_file():
        st = root.stat()
        return {str(root): (st.st_mtime, st.st_size)}
    if not root.is_dir():
        return {}
    out: Snapshot = {}
    iterator = root.rglob("*") if recursive else root.glob("*")
    for path in iterator:
        try:
            if not path.is_file():
                continue
            if not any(fnmatch.fnmatch(path.name, pat) for pat in patterns):
                continue
            st = path.stat()
        except OSError:
            continue
        out[str(path)] = (st.st_mtime, st.st_size)
    return out


def diff(old: Snapshot, new: Snapshot) -> list[tuple[str, str]]:
    """Return ``(event, path)`` pairs describing changes between snapshots."""
    events: list[tuple[str, str]] = []
    for path, meta in new.items():
        if path not in old:
            events.append(("created", path))
        elif old[path] != meta:
            events.append(("modified", path))
    events.extend(("deleted", path) for path in old if path not in new)
    return sorted(events, key=lambda e: e[1])


class FileRunner(TriggerRunner):
    """Fires one run per matching file event."""

    trigger_type = "file"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        trig = self.workflow.trigger
        assert isinstance(trig, FileTrigger)
        self.trig = trig
        self.root = self.engine.settings.resolve(trig.path)
        self._snapshot: Snapshot | None = None

    async def poll_once(self) -> list[tuple[str, str]]:
        """Take a snapshot, fire runs for changes since the previous one."""
        current = await asyncio.to_thread(
            snapshot, self.root, self.trig.patterns, self.trig.recursive
        )
        if self._snapshot is None:
            self._snapshot = current
            return []
        changes = [c for c in diff(self._snapshot, current) if c[0] in self.trig.events]
        self._snapshot = current
        for event, path in changes:
            p = Path(path)
            await self.fire({"event": event, "path": path, "name": p.name, "suffix": p.suffix})
        return changes

    async def run(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self.trig.interval)
