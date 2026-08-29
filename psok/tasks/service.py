"""Creating, changing and filing tasks -- the only place that does any of it.

There used to be three implementations of this. `create_task` the tool,
`POST /api/tasks`, and the To Do sync each resolved date hints, decided where a
task belonged, wrote the row, and tried to mirror it upstream -- separately, and
not quite alike. The drift was visible from the outside: the browser composer
could express less than the API, which could express less than the tool, and
none of them could name a list at all.

So: one service, three thin callers. A field added here reaches every surface at
once, and "where does a task go" has exactly one answer.

**Lists mirror Microsoft To Do.** When the connector is signed in, Graph owns
the lists and PSOK follows; a list created here is created there first, so it
reaches the phone rather than becoming a second organisation scheme nobody sees.
With nothing signed in, lists are local and say so.

**A local change is marked dirty, not pushed inline.** `dirty_at` is set on
every mutation and the sync's push half clears it. Writing to Graph inside the
request would put a network round trip in front of a checkbox, and a failed one
in front of the user's edit -- and the edit is the thing that must not be lost.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from psok.db.repositories import TaskListRepository, TaskRepository, is_my_day_list
from psok.scheduling.engine import AmbiguousDate, find_conflicts, resolve_date_hint

log = logging.getLogger(__name__)

# Assumed length of a work block when the caller gives no duration estimate.
DEFAULT_WORK_BLOCK_MINUTES = 60

SOURCE = "microsoft-todo"

#: What a My Day list is called when PSOK has to make one. Any of the names in
#: `MY_DAY_LIST_NAMES` is recognised; this is the one written.
MY_DAY_LIST_NAME = "My Day"

STATUSES = ("todo", "in_progress", "done", "cancelled")
PRIORITIES = ("low", "medium", "high")


class TaskError(ValueError):
    """Something the caller can fix, phrased for whoever asked.

    Deliberately not an exception the loop treats as a failure: every caller
    turns it into its own shape -- a `ToolResult.error` the model can act on, a
    400 the browser can show -- because "the date was ambiguous" is information,
    not a fault.
    """


@dataclass
class ListRef:
    """A list, and whether naming it did anything upstream."""

    id: int | None = None
    name: str | None = None
    external_id: str | None = None
    created: bool = False
    note: str = ""


@dataclass
class Written:
    """What a create or an update actually did, so callers can say so."""

    task_id: int
    list_ref: ListRef = field(default_factory=ListRef)
    routed_to: str = ""
    changed: dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")



def _hint(value: str | None, *, advice: str) -> datetime | None:
    if not value:
        return None
    try:
        return resolve_date_hint(value)
    except AmbiguousDate as exc:
        raise TaskError(f"{exc}. {advice}") from exc


def _stamp(when: datetime | None) -> str | None:
    return when.isoformat(sep=" ", timespec="seconds") if when else None


class TaskService:
    def __init__(
        self,
        tasks: TaskRepository | None = None,
        lists: TaskListRepository | None = None,
    ):
        self.tasks = tasks or TaskRepository()
        self.lists = lists or TaskListRepository()

    # ------------------------------------------------------------------ lists

    async def resolve_list(self, name: str | None, *, create: bool = True) -> ListRef:
        """Find the list the user meant, creating it when they clearly meant a new one.

        Matching is exact, then case-insensitive, then a unique prefix -- never
        an ambiguous one, because putting a task in one of two plausible lists
        is worse than asking.
        """
        if not (name or "").strip():
            row = self.lists.default()
            if row is None:
                return ListRef()
            return await self._adopt(row)

        wanted = name.strip()
        row = self.lists.by_name(wanted)
        if row is not None:
            return await self._adopt(row)
        if not create:
            known = ", ".join(r["name"] for r in self.lists.all()) or "none yet"
            raise TaskError(f"there is no list called '{wanted}'. Lists: {known}")
        return await self.create_list(wanted)

    async def _adopt(self, row: sqlite3.Row) -> ListRef:
        """Give a local-only list an upstream identity, once there is one to give.

        A list made while nothing was signed in has no `external_id`, and a task
        filed into it goes upstream to the *default* list -- so the next pull
        refiles that task into the default list and the user's chosen list
        quietly empties itself. Signing in has to heal that rather than leave a
        second, diverging organisation scheme behind.
        """
        if row["external_id"]:
            return ListRef(id=row["id"], name=row["name"], external_id=row["external_id"])

        external_id, note = await self._create_list_upstream(row["name"])
        if external_id:
            self.lists.update(
                row["id"], external_source=SOURCE, external_id=external_id
            )
        return ListRef(id=row["id"], name=row["name"], external_id=external_id, note=note)

    async def create_list(self, name: str) -> ListRef:
        """Create a list, upstream first so the id we store is Graph's own."""
        wanted = name.strip()
        if not wanted:
            raise TaskError("a list needs a name")

        external_id, note = await self._create_list_upstream(wanted)
        list_id = self.lists.create(
            wanted,
            external_source=SOURCE if external_id else None,
            external_id=external_id,
        )
        return ListRef(id=list_id, name=wanted, external_id=external_id, created=True, note=note)

    async def my_day_list(self) -> ListRef:
        """The list that *is* My Day, created if the account has not got one.

        Made upstream like any other list, so it appears in To Do beside the
        rest and the phone can add to it. That is the entire mechanism: there is
        no flag, no tag and no second copy -- see the note at the top of
        `psok/sync/microsoft_todo.py` for why nothing else survives the trip.
        """
        for row in self.lists.all():
            if is_my_day_list(row["name"]):
                return await self._adopt(row)
        return await self.create_list(MY_DAY_LIST_NAME)

    async def _default_list(self) -> ListRef:
        """Where a task goes when it leaves My Day.

        To Do's own default list, except when that *is* My Day: `default()`
        falls back to the first list when nothing is flagged, so on an account
        whose only list is My Day, taking a task out of My Day would move it
        into My Day. Anything else beats that; nothing else leaves the task
        unfiled, which is what a local-only task already is.
        """
        rows = [row for row in self.lists.all() if not is_my_day_list(row["name"])]
        if not rows:
            return ListRef()
        row = next((r for r in rows if r["is_default"]), rows[0])
        return await self._adopt(row)

    async def move(self, task_id: int, target: ListRef) -> str:
        """Put a task in another list, upstream included. Returns a note.

        Graph cannot move a task, so `move_remote_task` recreates it in the
        target and deletes the original -- which means the id changes and the
        local row has to be repointed at the new one. Doing that here rather
        than leaving `dirty_at` for the push is deliberate: the push sends
        `update_task` with the *new* list and the *old* task id, which To Do
        answers with a 404 forever.
        """
        from psok.sync.microsoft_todo import move_remote_task

        existing = self.tasks.get(task_id)
        if existing is None:
            raise TaskError(f"no task with id {task_id}")
        if existing["list_id"] == target.id:
            return ""

        source = self.lists.get(existing["list_id"]) if existing["list_id"] else None
        source_external = source["external_id"] if source is not None else None
        if not existing["external_id"]:
            # Never pushed, so there is nothing upstream to move. It goes to the
            # right list locally and the push creates it there.
            self.tasks.update(task_id, list_id=target.id)
            return f"moved to {target.name}"
        if not (source_external and target.external_id):
            # The task exists upstream but one of the two lists does not, so
            # there is no move to make -- and moving it locally would be undone
            # by the next pull, which files a task where To Do says it lives.
            raise TaskError(
                f"'{existing['title']}' is in Microsoft To Do but"
                f" {'its list' if not source_external else target.name} is not."
                " Sync first, then move it."
            )

        try:
            moved = await move_remote_task(
                existing, to_list=target.external_id, from_list=source_external
            )
        except Exception as exc:
            log.info("could not move task %s in Microsoft To Do: %s", task_id, exc)
            # Left exactly where it was, in both places. Moving it locally over a
            # failed upstream move would put PSOK and the phone into permanent
            # disagreement about which list holds it.
            raise TaskError(
                f"could not move '{existing['title']}' to {target.name} in Microsoft To Do."
                " It is still where it was."
            ) from exc

        if moved is None:
            # Signed out between the check above and here. Refused rather than
            # moved locally, for the reason the branch above gives.
            raise TaskError(
                "Microsoft To Do is not connected, so a task that lives there cannot be"
                " moved between lists. Connect it from Connectors and try again."
            )

        self.tasks.adopt_external(
            task_id,
            source=SOURCE,
            external_id=moved["external_id"],
            external_etag=moved.get("external_etag") or None,
        )
        self.tasks.update(task_id, list_id=target.id)
        return f"moved to {target.name} in Microsoft To Do"

    @staticmethod
    async def _create_list_upstream(name: str) -> tuple[str | None, str]:
        from psok.mcp import live
        from psok.sync.microsoft_todo import create_remote_list

        if live.connection(SOURCE) is None:
            return None, "kept in PSOK (no task connector is signed in)"
        try:
            external_id = await create_remote_list(name)
        except Exception as exc:
            log.info("could not create list %r in Microsoft To Do: %s", name, exc)
            return None, "kept locally -- Microsoft To Do could not be written to"
        return external_id, "created in Microsoft To Do"

    # ------------------------------------------------------------------ write

    async def create(
        self,
        title: str,
        *,
        notes: str | None = None,
        due_hint: str | None = None,
        scheduled_hint: str | None = None,
        reminder_hint: str | None = None,
        duration_estimate_minutes: int | None = None,
        priority: str | None = None,
        important: bool = False,
        add_to_my_day: bool = False,
        list_name: str | None = None,
        source: str = "user",
        check_conflicts: bool = True,
    ) -> Written:
        title = (title or "").strip()
        if not title:
            raise TaskError("a task needs a title")
        if priority and priority not in PRIORITIES:
            raise TaskError(f"priority must be one of {', '.join(PRIORITIES)}")

        due_at = _hint(
            due_hint,
            advice="Ask the user for a specific date or time rather than guessing.",
        )
        scheduled_at = _hint(
            scheduled_hint,
            advice="Ask the user to clarify when they'll work on it.",
        )
        reminder_at = _hint(
            reminder_hint,
            advice="Ask the user when they want to be reminded.",
        )

        if scheduled_at and check_conflicts:
            self._refuse_on_conflict(scheduled_at, duration_estimate_minutes)

        # My Day *is* a list, so asking for today is asking for that list. It
        # wins over a named one rather than being combined with it: To Do puts a
        # task in exactly one list, so "in My Day, in Groceries" has no meaning
        # to honour.
        list_ref = await (self.my_day_list() if add_to_my_day else self.resolve_list(list_name))
        external, routed_to = await self._create_upstream(
            title,
            notes=notes,
            due_at=due_at,
            reminder_at=reminder_at,
            priority=priority,
            important=important,
            list_external_id=list_ref.external_id,
        )

        task_id = self.tasks.create(
            title,
            notes=notes,
            due_at=_stamp(due_at),
            scheduled_at=_stamp(scheduled_at),
            duration_estimate_minutes=(
                int(duration_estimate_minutes) if duration_estimate_minutes else None
            ),
            priority=priority,
            source=source,
            reminder_at=_stamp(reminder_at),
            external_source=SOURCE if external else None,
            external_id=external["external_id"] if external else None,
            external_etag=(external.get("external_etag") or None) if external else None,
            list_id=list_ref.id,
            important=important,
            # Nothing upstream to update yet when the create already landed
            # there; a row that did not reach To Do is dirty so the next sync
            # carries it over rather than leaving it stranded locally.
            dirty_at=None if external else _now(),
        )
        return Written(task_id=task_id, list_ref=list_ref, routed_to=routed_to)

    def _refuse_on_conflict(self, scheduled_at: datetime, duration: int | None) -> None:
        # Without an estimate, assume a nominal block rather than skipping the
        # check: silently booking over an existing event is the worse failure.
        window = timedelta(minutes=int(duration) if duration else DEFAULT_WORK_BLOCK_MINUTES)
        conflicts = find_conflicts(scheduled_at, scheduled_at + window)
        if not conflicts:
            return
        listed = "; ".join(f"'{c.title}' {c.starts_at} to {c.ends_at}" for c in conflicts)
        raise TaskError(
            f"the requested work time conflicts with: {listed}. Propose another slot"
            " (find_free_slot can suggest one) or confirm with the user before overlapping."
        )

    @staticmethod
    async def _create_upstream(
        title: str,
        *,
        notes: str | None,
        due_at: datetime | None,
        reminder_at: datetime | None,
        priority: str | None,
        important: bool,
        list_external_id: str | None,
    ) -> tuple[dict[str, str] | None, str]:
        """Put the task in the user's real task list, where there is one.

        A failure here is never fatal. Losing what the user asked for because
        their task service was briefly unreachable is a far worse outcome than a
        local row the next sync pushes, so the task is always written locally and
        the answer says the upstream write did not happen.
        """
        from psok.sync.microsoft_todo import create_remote_task

        try:
            external = await create_remote_task(
                title,
                notes=notes,
                due_at=_stamp(due_at),
                reminder_at=_stamp(reminder_at),
                priority=priority,
                important=important,
                list_id=list_external_id,
            )
        except Exception as exc:
            log.info("could not create %r in Microsoft To Do: %s", title, exc)
            return None, "kept locally only -- Microsoft To Do could not be written to"

        if external is None:
            return None, "kept in PSOK (no task connector is signed in)"
        return external, "added to Microsoft To Do"

    async def update(
        self,
        task_id: int,
        *,
        title: str | None = None,
        notes: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        important: bool | None = None,
        add_to_my_day: bool | None = None,
        list_name: str | None = None,
        due_hint: str | None = None,
        scheduled_hint: str | None = None,
        reminder_hint: str | None = None,
        duration_estimate_minutes: int | None = None,
    ) -> Written:
        existing = self.tasks.get(task_id)
        if existing is None:
            raise TaskError(f"no task with id {task_id}")

        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if notes is not None:
            fields["notes"] = notes
        if status is not None:
            if status not in STATUSES:
                raise TaskError(f"status must be one of {', '.join(STATUSES)}")
            fields["status"] = status
        if priority is not None:
            if priority not in PRIORITIES:
                raise TaskError(f"priority must be one of {', '.join(PRIORITIES)}")
            fields["priority"] = priority
        if important is not None:
            fields["important"] = 1 if important else 0
        if duration_estimate_minutes is not None:
            fields["duration_estimate_minutes"] = int(duration_estimate_minutes)

        for hint, column, advice in (
            (due_hint, "due_at", "Ask the user to clarify the deadline."),
            (scheduled_hint, "scheduled_at", "Ask the user when they'll work on it."),
            (reminder_hint, "reminder_at", "Ask the user when to remind them."),
        ):
            when = _hint(hint, advice=advice)
            if when is not None:
                fields[column] = _stamp(when)

        # Both of these are the same operation: My Day is a list, so the sun is
        # a move to it and taking a task out of My Day is a move back to the
        # default list. `add_to_my_day` wins over a named list for the reason
        # `create` gives -- a task lives in one list, so the two cannot combine.
        list_ref = ListRef()
        target: ListRef | None = None
        if add_to_my_day is not None:
            target = await (self.my_day_list() if add_to_my_day else self._default_list())
        elif list_name is not None:
            target = await self.resolve_list(list_name)
        if target is not None:
            list_ref = target

        if not fields and target is None:
            raise TaskError("nothing to update")

        # Moving the time a reminder is owed makes an already-delivered one
        # stale: without this, pushing a task to tomorrow means never hearing
        # about it again, because it was announced today.
        if "reminder_at" in fields or "due_at" in fields:
            fields["reminded_at"] = None

        # The move goes first and goes now: it recreates the task upstream under
        # a new id, and the field edits below have to be marked against that id
        # rather than the one it is about to stop having.
        moved = ""
        if target is not None:
            moved = await self.move(task_id, target)
            existing = self.tasks.get(task_id) or existing

        if not fields:
            return Written(task_id=task_id, list_ref=list_ref, routed_to=moved)

        # Every local change owes the connector an update. Marked rather than
        # pushed, so a checkbox never waits on a network round trip.
        if existing["external_id"]:
            fields["dirty_at"] = _now()

        self.tasks.update(task_id, **fields)
        return Written(task_id=task_id, list_ref=list_ref, changed=fields, routed_to=moved)

    async def complete(self, task_id: int, *, done: bool = True) -> Written:
        return await self.update(task_id, status="done" if done else "todo")

    async def cancel(self, task_id: int) -> Written:
        """Soft-cancel. Nothing in PSOK deletes a task.

        A row deleted locally comes straight back on the next pull, so deleting
        one is a lie that lasts fifteen minutes.
        """
        return await self.update(task_id, status="cancelled")

    # ----------------------------------------------------------------- naming

    def list_names(self) -> list[str]:
        return [row["name"] for row in self.lists.all()]


def describe_task(row: sqlite3.Row, list_name: str | None = None) -> str:
    """One line about a task, for a model reading a tool result."""
    bits = [f"#{row['id']} {row['title']} [{row['status']}]"]
    if list_name:
        bits.append(f"in {list_name}")
    if row["important"]:
        bits.append("important")
    if is_my_day_list(list_name):
        bits.append("my day")
    for column, label in (
        ("due_at", "due"),
        ("scheduled_at", "scheduled"),
        ("reminder_at", "reminder"),
    ):
        if row[column]:
            bits.append(f"{label} {row[column]}")
    if row["external_source"]:
        bits.append(f"from {row['external_source']}")
    return " | ".join(bits)
