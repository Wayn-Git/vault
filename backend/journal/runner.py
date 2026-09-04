"""The clock the journal runs on.

Deliberately not part of `AutomationRunner` and not part of `ReminderRunner`.

Not automations, because an automation is an interval and this is a wall-clock
time: `every_minutes=1440` has no way to mean "at seven", `next_run_at` is
rescheduled as `now + delay` so it drifts by however long each run took, and an
automation runs a full unattended agent turn behind a gate that denies every
confirmation. A briefing is one model call over figures already gathered.

Not reminders, because this makes model calls that can take a minute, and a
reminder queued behind one is not a reminder -- the same argument `ReminderRunner`
makes for not being part of `AutomationRunner`.

Local naive clock, like reminders and unlike automations: "today" here means the
date on the user's own clock, and the journal is filed under that date.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from backend.config import load_journal_schedule
from backend.journal.service import JournalService

log = logging.getLogger(__name__)

#: A briefing at 07:00:45 is indistinguishable from one at 07:00:00, and the
#: check is three indexed reads.
TICK_SECONDS = 60


class JournalRunner:
    def __init__(self, service_factory=JournalService) -> None:
        self._task: asyncio.Task | None = None
        self._service_factory = service_factory

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="journal")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                # Sleep first, then check. Starting the app must not file an
                # entry in the same breath -- and `TestClient` runs the app's
                # lifespan, so a check-first loop would have every API test try
                # to write a briefing against whatever provider is configured.
                await asyncio.sleep(TICK_SECONDS)
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # one bad tick must not end the runner
                log.exception("journal tick failed")

    async def tick(self, now: datetime | None = None) -> list[str]:
        """File whatever this hour has come round for. Returns what was filed."""
        now = now or datetime.now()
        schedule = load_journal_schedule()
        service = self._service_factory()
        filed: list[str] = []

        for kind, enabled, hour in (
            ("briefing", schedule.briefing_enabled, schedule.briefing_hour),
            ("daily", schedule.review_enabled, schedule.review_hour),
            ("weekly", schedule.weekly_enabled, schedule.review_hour),
        ):
            if not enabled or now.hour < hour:
                continue
            if kind == "weekly" and now.weekday() != schedule.weekly_weekday:
                # A weekly review written on Wednesday about last week is worse
                # than none, so a week nobody opened PSOK on its review day
                # produces no rollup. The interface offers it on demand instead.
                continue
            entry = await service.fire(kind, date(now.year, now.month, now.day))
            if entry is not None:
                filed.append(kind)
                log.info("filed the %s for %s", kind, entry["entry_date"])
        return filed
