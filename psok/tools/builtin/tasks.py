"""Task and calendar tools.

The model passes fuzzy hints ("tomorrow"); these tools resolve them
deterministically through the scheduling engine and hand conflicts back through
the loop rather than guessing (ADR-0010).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from psok.db.repositories import CalendarRepository, TaskRepository
from psok.scheduling.engine import AmbiguousDate, find_conflicts, find_free_slot, resolve_date_hint
from psok.tools.base import RiskLevel, Tool, ToolContext, ToolResult

log = logging.getLogger(__name__)

# Assumed length of a work block when the model gives no duration estimate.
DEFAULT_WORK_BLOCK_MINUTES = 60


async def create_task(args: dict[str, Any], _: ToolContext) -> ToolResult:
    title = (args.get("title") or "").strip()
    if not title:
        return ToolResult.error("a task needs a title")

    due_at = None
    if args.get("due_date_hint"):
        try:
            due_at = resolve_date_hint(args["due_date_hint"])
        except AmbiguousDate as exc:
            return ToolResult.error(
                f"{exc}. Ask the user for a specific date or time rather than guessing."
            )

    scheduled_at = None
    if args.get("scheduled_hint"):
        try:
            scheduled_at = resolve_date_hint(args["scheduled_hint"])
        except AmbiguousDate as exc:
            return ToolResult.error(f"{exc}. Ask the user to clarify when they'll work on it.")

    reminder_at = None
    if args.get("reminder_hint"):
        try:
            reminder_at = resolve_date_hint(args["reminder_hint"])
        except AmbiguousDate as exc:
            return ToolResult.error(f"{exc}. Ask the user when they want to be reminded.")

    duration = args.get("duration_estimate_minutes")

    if scheduled_at:
        # Without an estimate, assume a nominal block rather than skipping the
        # check: silently booking over an existing event is the worse failure.
        window = timedelta(minutes=int(duration) if duration else DEFAULT_WORK_BLOCK_MINUTES)
        conflicts = find_conflicts(scheduled_at, scheduled_at + window)
        if conflicts:
            listed = "; ".join(f"'{c.title}' {c.starts_at} to {c.ends_at}" for c in conflicts)
            return ToolResult.error(
                f"the requested work time conflicts with: {listed}. Propose another slot"
                " (find_free_slot can suggest one) or confirm with the user before overlapping."
            )

    # Where the task belongs, if the user keeps their tasks somewhere. A local
    # row beside a connected To Do account is a second list nobody asked for:
    # it does not reach the user's phone, does not appear in My Day, and drifts
    # from the list they actually read. So the connected list is the default and
    # the local row becomes its mirror.
    external, routed_to = await _create_upstream(
        title,
        notes=args.get("notes"),
        due_at=due_at,
        reminder_at=reminder_at,
        priority=args.get("priority"),
    )

    task_id = TaskRepository().create(
        title,
        notes=args.get("notes"),
        due_at=due_at.isoformat() if due_at else None,
        scheduled_at=scheduled_at.isoformat() if scheduled_at else None,
        duration_estimate_minutes=int(duration) if duration else None,
        priority=args.get("priority"),
        source="agent",
        reminder_at=reminder_at.isoformat() if reminder_at else None,
        external_source=MICROSOFT_TODO if external else None,
        external_id=external["external_id"] if external else None,
        external_etag=(external.get("external_etag") or None) if external else None,
    )
    parts = [f"created task {task_id}: {title}"]
    if due_at:
        parts.append(f"due {due_at:%Y-%m-%d %H:%M}")
    if scheduled_at:
        parts.append(f"scheduled {scheduled_at:%Y-%m-%d %H:%M}")
    if reminder_at:
        parts.append(f"reminding at {reminder_at:%Y-%m-%d %H:%M}")
    elif due_at:
        parts.append("reminding at the deadline")
    parts.append(routed_to)
    return ToolResult.ok(", ".join(parts))


MICROSOFT_TODO = "microsoft-todo"


async def _create_upstream(
    title: str,
    *,
    notes: str | None,
    due_at,
    reminder_at,
    priority: str | None,
) -> tuple[dict[str, str] | None, str]:
    """Put the task in the user's real task list, where there is one.

    Returns the identity to mirror and a phrase saying where it went, so the
    model reports the truth rather than "created" for a row only PSOK can see.

    A failure here is never fatal. Losing what the user asked for because their
    task service was briefly unreachable would be a far worse outcome than a
    local row that the next sync reconciles, so the task is always written
    locally and the answer says the upstream write did not happen.
    """
    from psok.sync.microsoft_todo import create_remote_task

    try:
        external = await create_remote_task(
            title,
            notes=notes,
            due_at=due_at.isoformat(sep=" ", timespec="seconds") if due_at else None,
            reminder_at=(
                reminder_at.isoformat(sep=" ", timespec="seconds") if reminder_at else None
            ),
            priority=priority,
        )
    except Exception as exc:
        # SyncUnavailable and a transport failure land here alike: the user
        # cares that it did not reach their list, not which layer said so.
        log.info("could not create %r in Microsoft To Do: %s", title, exc)
        return None, "kept locally only — Microsoft To Do could not be written to"

    if external is None:
        return None, "kept in PSOK (no task connector is signed in)"
    return external, "added to Microsoft To Do"


async def update_task(args: dict[str, Any], _: ToolContext) -> ToolResult:
    repo = TaskRepository()
    task_id = int(args["task_id"])
    if repo.get(task_id) is None:
        return ToolResult.error(f"no task with id {task_id}")

    fields: dict[str, Any] = {}
    for key in ("title", "notes", "status", "priority", "duration_estimate_minutes"):
        if args.get(key) is not None:
            fields[key] = args[key]
    for hint_key, column in (
        ("due_date_hint", "due_at"),
        ("scheduled_hint", "scheduled_at"),
        ("reminder_hint", "reminder_at"),
    ):
        if args.get(hint_key):
            try:
                fields[column] = resolve_date_hint(args[hint_key]).isoformat()
            except AmbiguousDate as exc:
                return ToolResult.error(f"{exc}. Ask the user to clarify.")
    if not fields:
        return ToolResult.error("nothing to update")

    # Moving the time a reminder is owed makes an already-delivered one stale:
    # without this, pushing a task to tomorrow means never hearing about it
    # again, because it was announced today.
    if "reminder_at" in fields or "due_at" in fields:
        fields["reminded_at"] = None

    repo.update(task_id, **fields)
    return ToolResult.ok(f"updated task {task_id}: {', '.join(fields)}")


async def list_upcoming(args: dict[str, Any], _: ToolContext) -> ToolResult:
    rows = TaskRepository().upcoming(limit=int(args.get("limit") or 20))
    if not rows:
        return ToolResult.ok("no open tasks")
    lines = []
    for r in rows:
        bits = [f"#{r['id']} {r['title']} [{r['status']}]"]
        if r["due_at"]:
            bits.append(f"due {r['due_at']}")
        if r["scheduled_at"]:
            bits.append(f"scheduled {r['scheduled_at']}")
        if r["reminder_at"]:
            bits.append(f"reminder {r['reminder_at']}")
        if r["external_source"]:
            bits.append(f"from {r['external_source']}")
        lines.append(" | ".join(bits))
    return ToolResult.ok("\n".join(lines))


async def find_free_slot_tool(args: dict[str, Any], _: ToolContext) -> ToolResult:
    duration = int(args.get("duration_minutes") or 60)
    search_from = None
    if args.get("after_hint"):
        try:
            search_from = resolve_date_hint(args["after_hint"])
        except AmbiguousDate as exc:
            return ToolResult.error(str(exc))

    slot = find_free_slot(
        duration, search_from=search_from, search_days=int(args.get("search_days") or 7)
    )
    if slot is None:
        return ToolResult.ok(f"no free {duration}-minute slot found in the search window")
    return ToolResult.ok(
        f"free slot: {slot.starts_at:%Y-%m-%d %H:%M} to {slot.ends_at:%H:%M}"
        f" ({slot.starts_at.isoformat()})"
    )


async def create_calendar_event(args: dict[str, Any], _: ToolContext) -> ToolResult:
    try:
        starts = resolve_date_hint(args["start_hint"])
    except AmbiguousDate as exc:
        return ToolResult.error(f"{exc}. Ask the user for a specific start time.")
    duration = int(args.get("duration_minutes") or 60)
    ends = starts + timedelta(minutes=duration)

    conflicts = find_conflicts(starts, ends)
    if conflicts and not args.get("allow_overlap"):
        listed = "; ".join(f"'{c.title}' {c.starts_at} to {c.ends_at}" for c in conflicts)
        return ToolResult.error(
            f"conflicts with: {listed}. Pick another time, or pass allow_overlap after"
            " checking with the user."
        )

    event_id = CalendarRepository().create(
        args["title"], starts.isoformat(), ends.isoformat(), location=args.get("location")
    )
    return ToolResult.ok(
        f"created event {event_id}: {args['title']} at {starts:%Y-%m-%d %H:%M}-{ends:%H:%M}"
    )


async def list_calendar(args: dict[str, Any], _: ToolContext) -> ToolResult:
    days = int(args.get("days") or 7)
    now = datetime.now()
    rows = CalendarRepository().in_window(now.isoformat(), (now + timedelta(days=days)).isoformat())
    if not rows:
        return ToolResult.ok(f"no events in the next {days} days")
    return ToolResult.ok(
        "\n".join(f"#{r['id']} {r['title']}: {r['starts_at']} to {r['ends_at']}" for r in rows)
    )


_HINT = "Natural language is fine ('tomorrow', 'next tuesday at 3pm'); it is resolved exactly."


def tools() -> list[Tool]:
    return [
        Tool(
            name="create_task",
            description="Create a task. Pass date hints in natural language; they are resolved"
            " deterministically and conflicts are reported back rather than guessed at.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "due_date_hint": {"type": "string", "description": f"Deadline. {_HINT}"},
                    "scheduled_hint": {
                        "type": "string",
                        "description": f"When the user will work on it, distinct from the"
                        f" deadline. {_HINT}",
                    },
                    "reminder_hint": {
                        "type": "string",
                        "description": "When to notify the user on their desktop. Defaults to"
                        f" the deadline when omitted. {_HINT}",
                    },
                    "duration_estimate_minutes": {"type": "integer"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["title"],
            },
            handler=create_task,
            risk=RiskLevel.MEDIUM,
        ),
        Tool(
            name="update_task",
            description="Update an existing task's fields or status.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "done", "cancelled"],
                    },
                    "priority": {"type": "string"},
                    "due_date_hint": {"type": "string"},
                    "scheduled_hint": {"type": "string"},
                    "reminder_hint": {
                        "type": "string",
                        "description": "When to notify the user. Retiming a task clears any"
                        " reminder already delivered, so it is announced again at the new time.",
                    },
                    "duration_estimate_minutes": {"type": "integer"},
                },
                "required": ["task_id"],
            },
            handler=update_task,
            risk=RiskLevel.MEDIUM,
        ),
        Tool(
            name="list_upcoming",
            description="List open tasks, soonest deadline first.",
            parameters={"type": "object", "properties": {"limit": {"type": "integer"}}},
            handler=list_upcoming,
            risk=RiskLevel.LOW,
        ),
        Tool(
            name="find_free_slot",
            description="Find the first free window of a given length in the working calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "duration_minutes": {"type": "integer"},
                    "after_hint": {"type": "string", "description": f"Search from. {_HINT}"},
                    "search_days": {"type": "integer"},
                },
                "required": ["duration_minutes"],
            },
            handler=find_free_slot_tool,
            risk=RiskLevel.LOW,
        ),
        Tool(
            name="create_calendar_event",
            description="Create a calendar event. Conflicts are reported rather than overwritten.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_hint": {"type": "string", "description": f"Start time. {_HINT}"},
                    "duration_minutes": {"type": "integer"},
                    "location": {"type": "string"},
                    "allow_overlap": {"type": "boolean"},
                },
                "required": ["title", "start_hint"],
            },
            handler=create_calendar_event,
            risk=RiskLevel.MEDIUM,
        ),
        Tool(
            name="list_calendar",
            description="List calendar events in the next N days.",
            parameters={"type": "object", "properties": {"days": {"type": "integer"}}},
            handler=list_calendar,
            risk=RiskLevel.LOW,
        ),
    ]
