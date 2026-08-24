"""Reminders: the one thing PSOK says without being asked.

`tasks.due_at` has existed since the first schema and nothing ever read it, so a
deadline was a value you could store and then had to remember yourself. This is
the loop that reads it.

Two rules, both stated rather than implied:

**Reminders fire while PSOK is open.** Same rule as automations, for the same
reason ([architecture/automation.md](../docs/architecture/automation.md)): a
daemon that outlives the interface is a second process with its own lifecycle,
and nothing here is worth that. A reminder that came due while PSOK was shut is
delivered when it next starts -- late, and marked late, rather than silently
dropped.

**A reminder is announced exactly once.** `reminded_at` is claimed with a
conditional update before the notification is sent, so a restart mid-tick, or
two ticks overlapping, cannot produce two of them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from psok.db.repositories import TaskRepository
from psok.notify import notify
from psok.sync.microsoft_todo import SyncUnavailable
from psok.sync.microsoft_todo import sync as sync_microsoft_todo

log = logging.getLogger(__name__)

# Matched to the automation runner's tick. A reminder is not a stopwatch: a
# deadline is worth knowing about within half a minute, and a tighter loop would
# be a wakeup a second for a table that changes a few times a day.
TICK_SECONDS = 30

# Past this, a reminder is delivered with a note saying when it was actually
# due, rather than as if it had just come round. Being told "due now" about
# something that was due yesterday is worse than being told nothing.
LATE_AFTER = timedelta(minutes=5)

# How often to pull external task sources. Far slower than the reminder scan:
# this is somebody else's API, and a to-do list does not change every half
# minute. A sync is also available on demand from the API and the CLI.
SYNC_EVERY_SECONDS = 15 * 60


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _describe(due: str, now: datetime) -> str:
    """The body of the notification: when this was due, in words."""
    try:
        when = datetime.fromisoformat(due)
    except ValueError:
        return f"Due {due}"
    when = when.replace(tzinfo=None)
    late = now - when
    if late < LATE_AFTER:
        return f"Due {when:%H:%M}"
    if late < timedelta(days=1):
        hours = int(late.total_seconds() // 3600)
        if hours < 1:
            return f"Was due at {when:%H:%M}, {int(late.total_seconds() // 60)} minutes ago"
        return f"Was due at {when:%H:%M}, {hours} hour{'s' if hours != 1 else ''} ago"
    return f"Was due {when:%d %b at %H:%M}"


async def fire_due(now: datetime | None = None) -> int:
    """Announce every reminder that has come round. Returns how many were sent.

    The claim happens before the notification, not after. A notifier that hangs
    or a process killed between the two costs one missed reminder; doing it the
    other way round costs a repeat every thirty seconds until it succeeds, which
    on a machine with no notification daemon is forever.
    """
    moment = now or _now()
    repository = TaskRepository()
    sent = 0
    for task in repository.due_reminders(moment.isoformat(sep=" ", timespec="seconds")):
        if not repository.mark_reminded(task["id"], moment.isoformat(sep=" ", timespec="seconds")):
            continue  # another tick got there first
        due = task["reminder_at"] or task["due_at"]
        await notify(task["title"], _describe(due, moment))
        sent += 1
    return sent


class ReminderRunner:
    """Wakes twice a minute and announces whatever has come due.

    Deliberately not merged into `AutomationRunner`, whose lock serializes model
    turns that can take five minutes each. A reminder is a database read and a
    subprocess; queueing it behind a browser automation would make it arrive
    whenever that finished, which is not a reminder.
    """

    def __init__(self, manager_for=None) -> None:
        self._task: asyncio.Task | None = None
        # How the connector sync reaches the live MCP manager. Optional: without
        # it this loop is reminders only, which is what the CLI and the tests want.
        self.manager_for = manager_for
        self._next_sync = 0.0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="reminders")

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
                await asyncio.sleep(TICK_SECONDS)
                if sent := await fire_due():
                    log.info("delivered %d reminder(s)", sent)
                await self._maybe_sync()
            except asyncio.CancelledError:
                raise
            except Exception:  # one bad tick must not end the runner
                log.exception("reminder tick failed")

    async def _maybe_sync(self) -> None:
        """Pull connected task sources, well below the reminder cadence.

        Reminders are checked twice a minute because the cost is a single
        indexed read. A sync is network round trips against someone else's API,
        so it runs on its own much slower clock -- and a connector that is not
        signed in is a normal state, logged at debug and not retried harder.
        """
        if self.manager_for is None or time.monotonic() < self._next_sync:
            return
        self._next_sync = time.monotonic() + SYNC_EVERY_SECONDS
        try:
            report = await sync_microsoft_todo(await self.manager_for())
        except SyncUnavailable as exc:
            log.debug("Microsoft To Do sync skipped: %s", exc)
            return
        except Exception:
            log.exception("Microsoft To Do sync failed")
            return
        if report.created or report.updated or report.cancelled:
            log.info("%s", report.summary())
