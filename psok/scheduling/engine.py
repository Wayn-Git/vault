"""Deterministic scheduling (ADR-0010).

The model interprets; this module computes. Every date resolution and conflict
check happens here against the system clock -- never as LLM arithmetic.
Ambiguity is returned as structured data for the model to act on rather than
silently guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

DEFAULT_DUE_TIME = time(17, 0)
WORKDAY_START = time(9, 0)
WORKDAY_END = time(18, 0)


class AmbiguousDate(ValueError):
    """Raised when a hint cannot be resolved to one time. The caller reports this
    back through the agent loop rather than picking a value."""


@dataclass
class Conflict:
    event_id: int
    title: str
    starts_at: str
    ends_at: str


@dataclass
class FreeSlot:
    starts_at: datetime
    ends_at: datetime


def _combine(day: date, at: time | None) -> datetime:
    return datetime.combine(day, at or DEFAULT_DUE_TIME)


def resolve_date_hint(hint: str, *, now: datetime | None = None) -> datetime:
    """Resolve a natural-language date hint deterministically.

    Handles the common relative forms directly, then falls back to dateutil.
    Raises AmbiguousDate rather than guessing.
    """
    now = now or datetime.now()
    text = (hint or "").strip().lower()
    if not text:
        raise AmbiguousDate("no date given")

    explicit_time: time | None = None
    time_match = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text)
    if time_match and (time_match.group(3) or ":" in time_match.group(0)):
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridiem = time_match.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            explicit_time = time(hour, minute)
            text = text.replace(time_match.group(0), "").strip()

    if text in ("today", "tonight", ""):
        return _combine(now.date(), explicit_time)
    if text == "tomorrow":
        return _combine(now.date() + timedelta(days=1), explicit_time)
    if text == "yesterday":
        return _combine(now.date() - timedelta(days=1), explicit_time)

    in_match = re.fullmatch(r"in\s+(\d+)\s+(day|days|week|weeks|month|months|hour|hours)", text)
    if in_match:
        count, unit = int(in_match.group(1)), in_match.group(2).rstrip("s")
        if unit == "hour":
            return now + timedelta(hours=count)
        delta = {
            "day": timedelta(days=count),
            "week": timedelta(weeks=count),
        }.get(unit) or relativedelta(months=count)
        return _combine((now + delta).date(), explicit_time)

    weekday_match = re.fullmatch(r"(?:(?:next|this|on)\s+)?(" + "|".join(WEEKDAYS) + r")", text)
    if weekday_match:
        # "next friday" and "friday" both mean the next occurrence. English is
        # genuinely ambiguous about whether "next" skips a week; resolving to the
        # nearer date avoids silently scheduling something seven days late.
        target = WEEKDAYS[weekday_match.group(1)]
        ahead = (target - now.weekday()) % 7 or 7
        return _combine(now.date() + timedelta(days=ahead), explicit_time)

    if text == "next week":
        ahead = (0 - now.weekday()) % 7 or 7
        return _combine(now.date() + timedelta(days=ahead), explicit_time)

    try:
        parsed = dateutil_parser.parse(
            hint, default=_combine(now.date(), explicit_time), fuzzy=True
        )
    except (ValueError, OverflowError) as exc:
        raise AmbiguousDate(f"could not resolve '{hint}' to a specific date or time") from exc
    return parsed


def find_conflicts(starts_at: datetime, ends_at: datetime, repo=None) -> list[Conflict]:
    from psok.db.repositories import CalendarRepository

    repo = repo or CalendarRepository()
    rows = repo.overlapping(starts_at.isoformat(), ends_at.isoformat())
    return [
        Conflict(event_id=r["id"], title=r["title"], starts_at=r["starts_at"], ends_at=r["ends_at"])
        for r in rows
    ]


def find_free_slot(
    duration_minutes: int,
    *,
    search_from: datetime | None = None,
    search_days: int = 7,
    repo=None,
) -> FreeSlot | None:
    """Greedy scan for the first open workday window. v1 scope: not a solver."""
    from psok.db.repositories import CalendarRepository

    repo = repo or CalendarRepository()
    start = search_from or datetime.now()
    duration = timedelta(minutes=duration_minutes)

    for day_offset in range(search_days):
        day = (start + timedelta(days=day_offset)).date()
        cursor = (
            max(datetime.combine(day, WORKDAY_START), start)
            if day_offset == 0
            else datetime.combine(day, WORKDAY_START)
        )
        day_end = datetime.combine(day, WORKDAY_END)
        if cursor + duration > day_end:
            continue

        busy = repo.in_window(cursor.isoformat(), day_end.isoformat())
        for row in busy:
            if not row["busy"]:
                continue
            ev_start = dateutil_parser.parse(row["starts_at"])
            ev_end = dateutil_parser.parse(row["ends_at"])
            if ev_start - cursor >= duration:
                return FreeSlot(cursor, cursor + duration)
            cursor = max(cursor, ev_end)
        if cursor + duration <= day_end:
            return FreeSlot(cursor, cursor + duration)
    return None
