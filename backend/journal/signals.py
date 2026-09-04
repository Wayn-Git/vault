"""What actually happened, gathered before anything is written about it.

The division of labour is the one the rest of PSOK uses: the model interprets,
this module computes (ADR-0010). Every number a briefing or a review states
comes from here, from a query against the database, and the model is handed
those numbers rather than the tools to go and find some.

That is not only a correctness argument. An unattended agent turn runs behind a
gate that denies every confirmation, so the tools it could reach are a subset
nobody chose, and a briefing assembled that way would be built from whatever the
model happened to call. Here, the same query runs every morning.

**Two clocks and three shapes.** The database holds local-naive timestamps
written by Python and UTC timestamps written by SQLite's `datetime('now')`, and
SQLite compares all of them as plain strings:

* `tasks.*` -- local naive, **space** separator (`_normalise_task_timestamps`).
* `calendar_events.*` -- local naive, **"T"** separator (`create_calendar_event`
  writes `datetime.isoformat()`).
* anything defaulted to `datetime('now')` -- UTC.

`'T'` is 0x54 and `' '` is 0x20, so a bound in the wrong shape does not fail:
it silently excludes every row. Both formats are named constants below, and
each is used against the table it belongs to.

`messages` and `execution_logs` are deliberately absent. Their `created_at` is
UTC while a day here is local, so "turns today" would be wrong by the machine's
offset for part of every day -- and a number that is quietly wrong is worse than
a section that is honestly missing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from backend.db.repositories import CalendarRepository, TaskRepository
from backend.library.store import LibraryStore

log = logging.getLogger(__name__)

#: tasks.due_at / scheduled_at / completed_at
TASK_FMT = "%Y-%m-%d %H:%M:%S"
#: calendar_events.starts_at / ends_at
CALENDAR_FMT = "%Y-%m-%dT%H:%M:%S"

#: How many rows of any one kind are carried into the JSON and the prompt. The
#: true count travels beside the list, so a review can honestly say "41 open"
#: while naming twenty-five of them.
MAX_LISTED = 25

MAIL_TIMEOUT = 8.0


@dataclass
class Signals:
    """The day, or the week, as the database has it."""

    entry_date: str
    span: str  # "day" | "week"
    window: tuple[str, str]
    tasks: dict = field(default_factory=dict)
    calendar: dict = field(default_factory=dict)
    mail: dict = field(default_factory=dict)
    library: dict = field(default_factory=dict)
    #: source -> the sentence saying why that section is thin or absent.
    degraded: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "entry_date": self.entry_date,
            "span": self.span,
            "window": list(self.window),
            "tasks": self.tasks,
            "calendar": self.calendar,
            "mail": self.mail,
            "library": self.library,
            "degraded": self.degraded,
        }

    @classmethod
    def from_json(cls, data: dict) -> Signals:
        window = data.get("window") or ["", ""]
        return cls(
            entry_date=data.get("entry_date", ""),
            span=data.get("span", "day"),
            window=(window[0], window[1] if len(window) > 1 else ""),
            tasks=data.get("tasks") or {},
            calendar=data.get("calendar") or {},
            mail=data.get("mail") or {},
            library=data.get("library") or {},
            degraded=data.get("degraded") or {},
        )

    def is_quiet(self) -> bool:
        """Nothing measurable happened. Worth saying rather than dressing up."""
        return not (
            self.tasks.get("completed")
            or self.tasks.get("open_count")
            or self.calendar.get("events")
            or self.library.get("items")
        )


def window_for(day: date, span: str) -> tuple[datetime, datetime]:
    """The local-naive half-open window a day or a week covers."""
    if span == "week":
        start_day = day - timedelta(days=day.weekday())
        end_day = start_day + timedelta(days=7)
    else:
        start_day = day
        end_day = day + timedelta(days=1)
    return datetime.combine(start_day, time.min), datetime.combine(end_day, time.min)


def _task_row(row) -> dict:
    return {
        "title": row["title"],
        "due_at": row["due_at"],
        "completed_at": row["completed_at"],
        "important": bool(row["important"]),
    }


def _capped(rows: list, render) -> dict:
    return {"items": [render(row) for row in rows[:MAX_LISTED]], "total": len(rows)}


async def gather(
    day: date | None = None, *, span: str = "day", mail_timeout: float = MAIL_TIMEOUT
) -> Signals:
    """Everything a briefing or a review is allowed to be written from."""
    day = day or date.today()
    start, end = window_for(day, span)
    signals = Signals(
        entry_date=day.isoformat(),
        span=span,
        window=(start.strftime(TASK_FMT), end.strftime(TASK_FMT)),
    )

    tasks = TaskRepository()
    completed = tasks.completed_between(start.strftime(TASK_FMT), end.strftime(TASK_FMT))
    overdue = tasks.open_with_due_before(start.strftime(TASK_FMT))
    counts = tasks.counts()
    signals.tasks = {
        "completed": [_task_row(row) for row in completed[:MAX_LISTED]],
        "completed_count": len(completed),
        "overdue": [_task_row(row) for row in overdue[:MAX_LISTED]],
        "overdue_count": len(overdue),
        "open_count": counts.get("all", 0),
        "my_day_count": counts.get("my_day", 0),
        "important_count": counts.get("important", 0),
    }

    events = CalendarRepository().in_window(
        start.strftime(CALENDAR_FMT), end.strftime(CALENDAR_FMT)
    )
    signals.calendar = _capped(
        list(events),
        lambda row: {
            "title": row["title"],
            "starts_at": row["starts_at"],
            "ends_at": row["ends_at"],
            "location": row["location"],
        },
    )

    library = LibraryStore()
    if span == "week":
        items = library.consumed_between(
            start.date().isoformat(), (end.date() - timedelta(days=1)).isoformat()
        )
    else:
        items = library.consumed_on(day.isoformat())
    signals.library = _capped(
        list(items),
        lambda row: {
            "title": row["title"],
            "kind": row["kind"],
            "author": row["author"],
            "notes": row["notes"],
        },
    )

    signals.mail = await _mail(mail_timeout, signals.degraded)
    return signals


async def _mail(timeout: float, degraded: dict[str, str]) -> dict:
    """Unread counts, or the reason there are none.

    Nobody signed in is the ordinary state on a fresh machine, and a dashboard
    that shows `0 unread` when it simply cannot see the inbox has told the user
    something false. The reason goes in `degraded` and the count stays None.
    """
    from backend.mail import MailUnavailable, unread_count

    try:
        counts = await asyncio.wait_for(unread_count(), timeout=timeout)
    except MailUnavailable as exc:
        degraded["mail"] = str(exc)
        return {"unread": None, "threads": None}
    except TimeoutError:
        degraded["mail"] = f"Gmail did not answer within {timeout:.0f}s"
        return {"unread": None, "threads": None}
    except Exception as exc:
        log.warning("mail signal unavailable: %s", exc)
        degraded["mail"] = f"Gmail could not be read: {exc}"
        return {"unread": None, "threads": None}
    return {"unread": counts["messages"], "threads": counts["threads"]}


def _lines(heading: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [heading, *[f"  - {item}" for item in items]]


def render(signals: Signals) -> str:
    """The signals as plain text, for a model to write from.

    Deliberately flat and boring. This is evidence, not prose: whatever the
    model produces has to be checkable against these lines.
    """
    out: list[str] = [
        f"date: {signals.entry_date} ({'the week beginning ' if signals.span == 'week' else ''}"
        f"{signals.window[0][:10]})",
    ]

    tasks = signals.tasks
    out.append(
        f"tasks: {tasks.get('completed_count', 0)} completed,"
        f" {tasks.get('overdue_count', 0)} overdue,"
        f" {tasks.get('open_count', 0)} open in total,"
        f" {tasks.get('my_day_count', 0)} in My Day"
    )
    out += _lines(
        "completed:",
        [f"{t['title']}" + (f" (was due {t['due_at']})" if t["due_at"] else "")
         for t in tasks.get("completed", [])],
    )
    out += _lines(
        "overdue:",
        [f"{t['title']} (due {t['due_at']})" for t in tasks.get("overdue", [])],
    )

    calendar = signals.calendar
    out.append(f"calendar: {calendar.get('total', 0)} events")
    out += _lines(
        "events:",
        [
            f"{e['starts_at']} to {e['ends_at']}: {e['title']}"
            + (f" at {e['location']}" if e.get("location") else "")
            for e in calendar.get("items", [])
        ],
    )

    unread = signals.mail.get("unread")
    out.append("mail: unavailable" if unread is None else f"mail: {unread} unread in the inbox")

    library = signals.library
    out.append(f"library: {library.get('total', 0)} items logged")
    out += _lines(
        "logged:",
        [
            f"{i['title']}" + (f" by {i['author']}" if i.get("author") else "")
            + (f" -- {i['notes']}" if i.get("notes") else "")
            for i in library.get("items", [])
        ],
    )

    if signals.degraded:
        out += _lines(
            "unavailable, and not to be guessed at:",
            [f"{source}: {reason}" for source, reason in signals.degraded.items()],
        )

    return "\n".join(out)
