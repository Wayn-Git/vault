"""Task and calendar tools.

The model passes fuzzy hints ("tomorrow"); these tools resolve them
deterministically through the scheduling engine and hand conflicts back through
the loop rather than guessing (ADR-0010).

Everything a task tool actually does lives in `psok.tasks.service`, which the
API and the To Do sync also call. These handlers translate arguments in and
phrase results out; they hold no logic of their own, because the three copies
that used to hold it drifted apart in exactly the ways you would expect.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from psok.db.repositories import CalendarRepository, TaskListRepository, TaskRepository
from psok.scheduling.engine import AmbiguousDate, find_conflicts, find_free_slot, resolve_date_hint
from psok.tasks.service import TaskError, TaskService, describe_task
from psok.tools.base import RiskLevel, Tool, ToolContext, ToolResult

log = logging.getLogger(__name__)

MICROSOFT_TODO = "microsoft-todo"


def _service() -> TaskService:
    return TaskService()


async def create_task(args: dict[str, Any], _: ToolContext) -> ToolResult:
    try:
        written = await _service().create(
            args.get("title") or "",
            notes=args.get("notes"),
            due_hint=args.get("due_date_hint"),
            scheduled_hint=args.get("scheduled_hint"),
            reminder_hint=args.get("reminder_hint"),
            duration_estimate_minutes=args.get("duration_estimate_minutes"),
            priority=args.get("priority"),
            important=bool(args.get("important")),
            add_to_my_day=bool(args.get("add_to_my_day")),
            list_name=args.get("list"),
            source="agent",
        )
    except TaskError as exc:
        return ToolResult.error(str(exc))
    return ToolResult.ok(_phrase(written))


async def create_tasks(args: dict[str, Any], _: ToolContext) -> ToolResult:
    """Several tasks, one call.

    "Add milk and eggs to groceries" is one intention. As two `create_task`
    calls it costs two model round trips, which on a slow model is most of a
    minute of waiting for something the user said in one breath.
    """
    titles = [t.strip() for t in (args.get("titles") or []) if str(t).strip()]
    if not titles:
        return ToolResult.error("create_tasks needs at least one title")

    service = _service()
    made: list[str] = []
    failed: list[str] = []
    routed = ""
    for title in titles:
        try:
            written = await service.create(
                title,
                due_hint=args.get("due_date_hint"),
                reminder_hint=args.get("reminder_hint"),
                priority=args.get("priority"),
                important=bool(args.get("important")),
                add_to_my_day=bool(args.get("add_to_my_day")),
                list_name=args.get("list"),
                source="agent",
            )
        except TaskError as exc:
            failed.append(f"{title} ({exc})")
            continue
        made.append(f"#{written.task_id} {title}")
        routed = written.routed_to
        where = written.list_ref

    if not made:
        return ToolResult.error("nothing was created: " + "; ".join(failed))

    parts = [f"created {len(made)}: {', '.join(made)}"]
    if where.name:
        parts.append(f"in {where.name}")
    if routed:
        parts.append(routed)
    if failed:
        parts.append(f"could not create: {'; '.join(failed)}")
    return ToolResult.ok(", ".join(parts))


def _phrase(written) -> str:
    row = TaskRepository().get(written.task_id)
    parts = [f"created task {written.task_id}: {row['title']}"]
    if row["due_at"]:
        parts.append(f"due {row['due_at']}")
    if row["scheduled_at"]:
        parts.append(f"scheduled {row['scheduled_at']}")
    if row["reminder_at"]:
        parts.append(f"reminding at {row['reminder_at']}")
    elif row["due_at"]:
        parts.append("reminding at the deadline")
    if row["important"]:
        parts.append("marked important")
    if row["my_day_on"]:
        parts.append("in My Day")
    if written.list_ref.name:
        parts.append(f"in {written.list_ref.name}")
        if written.list_ref.created:
            parts.append(f"a new list, {written.list_ref.note}")
    parts.append(written.routed_to)
    return ", ".join(p for p in parts if p)


async def update_task(args: dict[str, Any], _: ToolContext) -> ToolResult:
    try:
        written = await _service().update(
            int(args["task_id"]),
            title=args.get("title"),
            notes=args.get("notes"),
            status=args.get("status"),
            priority=args.get("priority"),
            important=args.get("important"),
            add_to_my_day=args.get("add_to_my_day"),
            list_name=args.get("list"),
            due_hint=args.get("due_date_hint"),
            scheduled_hint=args.get("scheduled_hint"),
            reminder_hint=args.get("reminder_hint"),
            duration_estimate_minutes=args.get("duration_estimate_minutes"),
        )
    except TaskError as exc:
        return ToolResult.error(str(exc))
    named = ", ".join(k for k in written.changed if k not in ("dirty_at", "reminded_at"))
    return ToolResult.ok(f"updated task {written.task_id}: {named}")


async def list_task_lists(args: dict[str, Any], _: ToolContext) -> ToolResult:
    rows = TaskListRepository().all()
    if not rows:
        return ToolResult.ok("no lists yet; tasks go to the default list")
    counts = TaskRepository().counts()
    lines = []
    for row in rows:
        open_tasks = counts.get(f"list:{row['id']}", 0)
        mark = " (default)" if row["is_default"] else ""
        where = "" if row["external_id"] else " — local only, not in Microsoft To Do"
        lines.append(f"{row['name']}{mark}: {open_tasks} open{where}")
    return ToolResult.ok("\n".join(lines))


BUCKETS = ("my_day", "missed", "important", "general", "completed", "all")


async def list_upcoming(args: dict[str, Any], _: ToolContext) -> ToolResult:
    """Open tasks, or one named bucket, or one named list."""
    tasks = TaskRepository()
    lists = TaskListRepository()
    limit = int(args.get("limit") or 20)

    wanted_list = (args.get("list") or "").strip()
    if wanted_list:
        row = lists.by_name(wanted_list)
        if row is None:
            known = ", ".join(r["name"] for r in lists.all()) or "none yet"
            return ToolResult.error(f"there is no list called '{wanted_list}'. Lists: {known}")
        rows = tasks.bucket("list", list_id=row["id"], limit=limit)
        heading = row["name"]
    else:
        bucket = (args.get("bucket") or "all").strip()
        if bucket not in BUCKETS:
            return ToolResult.error(f"bucket must be one of {', '.join(BUCKETS)}")
        rows = tasks.bucket(bucket, limit=limit)
        heading = bucket.replace("_", " ")

    if not rows:
        return ToolResult.ok(f"no tasks in {heading}")

    names = {row["id"]: row["name"] for row in lists.all(include_retired=True)}
    lines = [describe_task(r, names.get(r["list_id"])) for r in rows]
    return ToolResult.ok(f"{heading} ({len(rows)}):\n" + "\n".join(lines))


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
_LIST = (
    "Which of the user's lists it goes in, by name -- 'Groceries', 'College'."
    " Matched loosely against the lists they have; a name that matches none creates"
    " a new list. Omit it and the task goes to their default list."
)


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
                    "list": {"type": "string", "description": _LIST},
                    "important": {
                        "type": "boolean",
                        "description": "The user flagged this as important. Independent of any"
                        " deadline: an important task with no date is a normal thing.",
                    },
                    "add_to_my_day": {
                        "type": "boolean",
                        "description": "Put it in today's My Day. Use when the user says they"
                        " will do it today, which is different from it being due today.",
                    },
                },
                "required": ["title"],
            },
            handler=create_task,
            risk=RiskLevel.MEDIUM,
        ),
        Tool(
            name="create_tasks",
            description="Create several tasks at once, sharing a list and dates. Prefer this"
            " over repeated create_task calls when the user names more than one thing:"
            " 'add milk and eggs to groceries' is one call, not two.",
            parameters={
                "type": "object",
                "properties": {
                    "titles": {"type": "array", "items": {"type": "string"}},
                    "list": {"type": "string", "description": _LIST},
                    "due_date_hint": {"type": "string", "description": f"Deadline. {_HINT}"},
                    "reminder_hint": {"type": "string", "description": f"Reminder. {_HINT}"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                    "important": {"type": "boolean"},
                    "add_to_my_day": {"type": "boolean"},
                },
                "required": ["titles"],
            },
            handler=create_tasks,
            risk=RiskLevel.MEDIUM,
        ),
        Tool(
            name="list_task_lists",
            description="The user's task lists, with how many open tasks each holds.",
            parameters={"type": "object", "properties": {}},
            handler=list_task_lists,
            risk=RiskLevel.LOW,
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
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                    "important": {"type": "boolean"},
                    "add_to_my_day": {
                        "type": "boolean",
                        "description": "true puts it in today's My Day, false takes it out.",
                    },
                    "list": {"type": "string", "description": _LIST},
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
            description="List tasks: everything open by default, or one bucket, or one list.",
            parameters={
                "type": "object",
                "properties": {
                    "bucket": {
                        "type": "string",
                        "enum": list(BUCKETS),
                        "description": "my_day is what the user means to do today; missed is"
                        " overdue and still open; important is flagged regardless of date;"
                        " general has no date at all.",
                    },
                    "list": {
                        "type": "string",
                        "description": "Only tasks in this list. Overrides bucket.",
                    },
                    "limit": {"type": "integer"},
                },
            },
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
