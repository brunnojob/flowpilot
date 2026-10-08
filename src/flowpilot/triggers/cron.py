"""Cron and fixed-interval triggers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

from flowpilot.models import CronTrigger, IntervalTrigger
from flowpilot.triggers.base import TriggerRunner

MAX_SLEEP = 60.0


def next_cron_time(
    expression: str, tz: str | None = None, after: datetime | None = None
) -> datetime:
    """Return the next fire time (timezone-aware) of ``expression`` after ``after``."""
    zone = ZoneInfo(tz) if tz else datetime.now().astimezone().tzinfo or timezone.utc
    base = (after or datetime.now(timezone.utc)).astimezone(zone)
    nxt: datetime = croniter(expression, base).get_next(datetime)
    return nxt


class CronRunner(TriggerRunner):
    """Fires at each cron occurrence. Missed occurrences while down are not replayed."""

    trigger_type = "cron"

    async def run(self) -> None:
        trig = self.workflow.trigger
        assert isinstance(trig, CronTrigger)
        last: datetime | None = None
        while True:
            now = datetime.now(timezone.utc)
            target = next_cron_time(trig.cron, trig.timezone, after=max(now, last) if last else now)
            self.next_fire = target
            while True:
                remaining = (target - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    break
                # Sleep in bounded chunks so clock jumps / suspend are handled.
                await asyncio.sleep(min(remaining, MAX_SLEEP))
            last = target
            await self.fire({"scheduled_at": target.isoformat()})


class IntervalRunner(TriggerRunner):
    """Fires every ``seconds`` seconds."""

    trigger_type = "interval"

    async def run(self) -> None:
        trig = self.workflow.trigger
        assert isinstance(trig, IntervalTrigger)
        if trig.run_on_start:
            await self.fire({"scheduled_at": datetime.now(timezone.utc).isoformat()})
        while True:
            self.next_fire = datetime.now(timezone.utc) + timedelta(seconds=trig.seconds)
            await asyncio.sleep(trig.seconds)
            await self.fire({"scheduled_at": datetime.now(timezone.utc).isoformat()})
