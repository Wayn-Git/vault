"""Keep the local task store and Microsoft To Do in step, both directions.

**To Do is the source of truth.** Its lists, its ids, its statuses. PSOK holds a
mirror so `due_at` and `reminder_at` are readable by the reminder loop and a
task can be cross-referenced against the notes vault without a network round
trip -- and so the buckets (My Day, Missed, Important) have something local to
query.

**Push, then pull, in that order.** A local edit is marked `dirty_at` when it
happens rather than written through inline, because a checkbox must not wait on
a network round trip and an edit must not be lost to a failed one. The push half
walks the dirty rows and sends them; the pull half then overwrites from Graph.
Doing it in that order is what removes the need for a merge algorithm: by the
time the pull runs, upstream already has the local changes, so "last write wins"
and "the local change wins" are the same outcome.

This replaces an earlier one-way design. Pulling only meant ticking a task in
PSOK never reached the phone, which made the local copy a second list that
drifted -- the exact failure the write-through on create was added to avoid.

Four properties this depends on, each load-bearing:

- **Identity, not position.** Rows are keyed on `(external_source,
  external_id)` behind a unique index, so pulling twice updates one row rather
  than making two. The mutation check for this is to drop the index and watch
  the duplicate appear.
- **PSOK-only fields are never overwritten.** `scheduled_at`,
  `duration_estimate_minutes` has no counterpart in To Do -- a
  pull that wrote every column would erase them on every tick. `notes` used to
  be in this set by accident rather than by design: it is To Do's `body`, PSOK
  seeds it from there on create, and leaving it out meant a body edited on the
  phone never propagated again. It is synced now.
- **A task that vanishes is cancelled, not deleted.** An empty or partial
  response is indistinguishable from an emptied account, and deleting rows on
  the strength of one is unrecoverable. The same rule covers a list.
- **Pushing is best effort and never blocks the pull.** A row whose upstream
  write fails keeps its `dirty_at` and is tried again next tick. The alternative
  -- abandoning the sync on the first failure -- would let one unwritable task
  stop every other task from updating.

The connector is reached through the live registry's manager, so this uses the
process that is already running and the account already signed in -- not a
second subprocess and not a second sign-in.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psok.db.repositories import TaskListRepository, TaskRepository

log = logging.getLogger(__name__)

SERVER = "microsoft-todo"
#: Where My Day lives, and why it is not a field.
#:
#: To Do's own My Day is not reachable. Verified against the live account on
#: 2026-08-28, not inferred from documentation: `$select=showInMyDay` and
#: `isInMyDay` both fail with "Could not find a property named ... on type
#: 'microsoft.graph.todoTask'" on v1.0 *and* beta; the live beta `$metadata`
#: lists twenty-one properties on `todoTask` and not one of them contains
#: "day"; there is no `myDay` well-known list; the legacy `/me/outlook/tasks`
#: surface has no such field either; and every MAPI extended-property probe
#: came back empty. My Day lives in To Do's client, not in its API.
#:
#: A category named "My Day" was tried next, and round-tripped -- but failed at
#: the thing that matters: a task added through To Do's own My Day carries no
#: such tag, so PSOK's My Day and the phone's showed different tasks, which is
#: the original problem restated. What both ends can see is an ordinary list.
#: So My Day *is* a list here, named in `psok.db.repositories.MY_DAY_LIST_NAMES`,
#: and putting a task in it means moving it there -- see `move_remote_task`.
#:
#: The cost, stated rather than hidden: To Do puts a task in exactly one list,
#: so this is a move and not an overlay. A task in My Day is no longer in the
#: list it came from, and To Do's own My Day still sits above it in the sidebar
#: doing its own thing. Tasks have to be added to the list, not to that.
MY_DAY_LIST_NAME = "My Day"


SOURCE = "microsoft-todo"

# To Do's own statuses, mapped onto the four this schema allows. `waitingOnOthers`
# and `deferred` are open work someone is still on the hook for, so they land on
# 'todo' rather than inventing a status the CHECK constraint would reject.
STATUS = {
    "notStarted": "todo",
    "inProgress": "in_progress",
    "waitingOnOthers": "todo",
    "deferred": "todo",
    "completed": "done",
}

PRIORITY = {"high": "high", "normal": "medium", "low": "low"}
REVERSE_PRIORITY = {"high": "high", "medium": "normal", "low": "low"}

# Going the other way, the four local statuses collapse to the two Graph
# accepts on a write. `in_progress` maps to `inProgress`; `cancelled` has no
# To Do equivalent and is sent as completed, because a task the user gave up
# on should stop appearing on their phone.
REVERSE_STATUS = {
    "todo": "notStarted",
    "in_progress": "inProgress",
    "done": "completed",
    "cancelled": "completed",
}

# How many pages of a listing to walk before giving up and saying so. Far
# above any real To Do account; it exists so a server that always returns a
# cursor cannot spin here forever.
MAX_PAGES = 50


class TruncatedListing(RuntimeError):
    """A listing came back short and said so.

    Raised rather than returned because the caller's next move -- deciding which
    local tasks no longer exist upstream -- is only safe on a complete answer.
    """


class SyncUnavailable(RuntimeError):
    """The connector is not running or not signed in. Not an error to retry hard."""


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    cancelled: int = 0
    lists: int = 0
    lists_created: int = 0
    lists_retired: int = 0
    pushed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "cancelled": self.cancelled,
            "lists": self.lists,
            "lists_created": self.lists_created,
            "lists_retired": self.lists_retired,
            "pushed": self.pushed,
        }

    def summary(self) -> str:
        parts = []
        if self.pushed:
            parts.append(f"{self.pushed} sent")
        if self.created:
            parts.append(f"{self.created} new")
        if self.updated:
            parts.append(f"{self.updated} updated")
        if self.cancelled:
            parts.append(f"{self.cancelled} gone from To Do")
        if self.lists_created:
            parts.append(f"{self.lists_created} new lists")
        if self.lists_retired:
            parts.append(f"{self.lists_retired} lists gone")
        if not parts:
            return f"already up to date with Microsoft To Do ({self.lists} lists)"
        return f"synced Microsoft To Do: {', '.join(parts)}"


def _timestamp(value: Any) -> str | None:
    """Graph's `{dateTime, timeZone}` shape, or a plain string, as local naive ISO.

    The rest of PSOK stores naive local timestamps and compares them as strings,
    so a value carrying an offset has to be converted rather than stored as-is:
    a reminder held as UTC would fire at the wrong hour, silently.
    """
    if not value:
        return None
    raw = value.get("dateTime") if isinstance(value, dict) else value
    if not isinstance(raw, str) or not raw:
        return None
    zone = value.get("timeZone") if isinstance(value, dict) else None
    text = raw.replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None and (zone or "").upper() == "UTC":
        when = when.replace(tzinfo=UTC)
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when.isoformat(sep=" ", timespec="seconds")


def _completed_at(item: dict, existing: Any = None) -> str | None:
    """When the task was finished, without losing a day or a minute.

    To Do stamps `completedDateTime` as the completion *date* at midnight UTC.
    Read as an instant and converted to local time, that lands on the previous
    day anywhere west of Greenwich -- so a task ticked off in the morning came
    back from the sync stamped yesterday, and dropped straight out of "what I
    finished today". The date is what the field means, so the date is what is
    kept, unshifted.

    And PSOK knows the minute the box was ticked where To Do only knows the day,
    so a local stamp already on that date wins over midnight. Otherwise every
    completion time collapsed to 00:00 on the first sync after the tick.
    """
    raw = item.get("completedDateTime")
    if not raw:
        return None
    text = raw.get("dateTime") if isinstance(raw, dict) else raw
    if not isinstance(text, str) or not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _timestamp(raw)
    if when.hour or when.minute or when.second:
        stamped = _timestamp(raw)  # a real instant; convert it the ordinary way
    else:
        stamped = when.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    if not stamped or existing is None:
        return stamped
    try:
        local = existing["completed_at"]
    except (IndexError, KeyError):
        local = None
    return str(local) if local and str(local)[:10] == stamped[:10] else stamped


def _text_of(result: Any) -> str:
    from psok.mcp.manager import normalize_result

    return normalize_result(result).content


def _payload(result: Any) -> Any:
    """The JSON an MCP text result is carrying, or None.

    MCP servers answer in text blocks. This one returns JSON in them; a server
    that stopped doing so would produce nothing here rather than a wrong sync.
    """
    text = _text_of(result).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _items(payload: Any, *keys: str) -> list[dict]:
    """The list inside a response, whichever of the usual shapes it arrived in."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (*keys, "value", "items", "results", "data"):
        found = payload.get(key)
        if isinstance(found, list):
            return [item for item in found if isinstance(item, dict)]
    return []


async def _paged(connection: Any, tool: str, arguments: dict, *keys: str) -> list[dict]:
    """Every page of a listing, not just the first.

    Both `list_task_lists` and `list_tasks` take `cursor`/`maxResults` and
    return one page. Reading only the first silently truncated any list past the
    server's page size -- and a truncated pull is indistinguishable from tasks
    having been deleted, which `_retire_missing` would then cancel. So this is
    not an optimisation; it is what stops a large list cancelling itself.
    """
    out: list[dict] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        page = {**arguments, "cursor": cursor} if cursor else arguments
        payload = _payload(await connection.call(tool, page))
        out.extend(_items(payload, *keys))
        if not isinstance(payload, dict):
            return out
        cursor = (
            payload.get("nextCursor")
            or payload.get("cursor")
            or payload.get("continuationToken")
        )
        if not cursor:
            # This server signals more pages with `hasMore`, not by returning a
            # cursor field this code recognised -- so a truncated listing looked
            # exactly like a complete one. That matters more than it sounds:
            # `_retire_missing` cancels every local task the pull did not see,
            # so a silently short page would mark real tasks cancelled.
            if payload.get("hasMore"):
                log.warning(
                    "%s reports more pages but returned no cursor; the listing is"
                    " incomplete and retiring is skipped this pass",
                    tool,
                )
                raise TruncatedListing(tool)
            return out
    log.warning("%s stopped after %d pages; some items may be missing", tool, MAX_PAGES)
    return out


async def default_list_id(connection: Any) -> str | None:
    """The list a task belongs in when nobody said which.

    Microsoft marks one list `defaultList` -- it is "Tasks", the one To Do opens
    on -- and that is where a task the user did not file belongs. Falling back to
    the first list would put things in whichever list happened to sort first,
    which is not a default so much as a coin toss.
    """
    lists = await _paged(connection, "list_task_lists", {}, "lists", "taskLists")
    for task_list in lists:
        if task_list.get("wellknownListName") == "defaultList":
            return task_list.get("id")
    return lists[0].get("id") if lists else None


async def create_remote_list(name: str) -> str | None:
    """Create a To Do list and return its Graph id, or None if nothing is signed in."""
    from psok.mcp import live

    connection = live.connection(SERVER)
    if connection is None:
        return None
    created = _payload(await connection.call("create_task_list", {"displayName": name}))
    if not isinstance(created, dict):
        raise SyncUnavailable("Microsoft To Do did not describe the list it created")
    item = created.get("list") if isinstance(created.get("list"), dict) else created
    external_id = item.get("id")
    if not external_id:
        raise SyncUnavailable("Microsoft To Do created the list but returned no id")
    return str(external_id)


async def rename_remote_list(external_id: str, name: str) -> None:
    from psok.mcp import live

    connection = live.connection(SERVER)
    if connection is None:
        return
    await connection.call("update_task_list", {"listId": external_id, "displayName": name})


def _task_arguments(
    *,
    title: str | None = None,
    notes: str | None = None,
    due_at: str | None = None,
    reminder_at: str | None = None,
    priority: str | None = None,
    important: bool = False,
    status: str | None = None,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """The Graph-shaped fields for a create or an update.

    Timestamps go over as ISO-8601 local strings, which is what the server's own
    schema documents for the host timezone. They are stored locally in exactly
    that form, so no conversion happens on the way out and none is needed on the
    way back.
    """
    arguments: dict[str, Any] = {}
    if title is not None:
        arguments["title"] = title
    if notes is not None:
        arguments["body"] = notes
    if due_at is not None:
        arguments["dueDateTime"] = due_at.replace(" ", "T")
    if reminder_at is not None:
        arguments["reminderDateTime"] = reminder_at.replace(" ", "T")
    # To Do has one axis where PSOK has two. `important` is the user's flag and
    # wins; `priority` is the model's advisory guess and only speaks when the
    # user has not.
    if important:
        arguments["importance"] = "high"
    elif priority:
        arguments["importance"] = REVERSE_PRIORITY.get(priority, "normal")
    if status is not None:
        arguments["status"] = REVERSE_STATUS.get(status, "notStarted")
    if categories is not None:
        # Sent whole because Graph replaces the array rather than merging it.
        # The caller is responsible for having merged first -- see `_categories_for`.
        arguments["categories"] = categories
    return arguments


def _categories_for(row: Any) -> list[str]:
    """The full category list to send back.

    Built from the categories the last pull saw rather than from nothing,
    because Graph's write is a replace: a shorter array deletes every tag left
    out of it. PSOK writes none of its own -- My Day is a list -- so this hands
    back exactly what the user already had.
    """
    try:
        kept = json.loads(row["external_categories"] or "[]")
    except (TypeError, ValueError, IndexError, KeyError):
        return []
    return [c for c in kept if isinstance(c, str)]


def _identity(payload: Any, *, what: str) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise SyncUnavailable(f"Microsoft To Do did not describe the {what} it wrote")
    # Some builds wrap the item; accept either shape rather than failing over a
    # nesting difference.
    item = payload.get("task") if isinstance(payload.get("task"), dict) else payload
    external_id = item.get("id")
    if not external_id:
        raise SyncUnavailable(f"Microsoft To Do wrote the {what} but returned no id")
    return {
        "external_id": str(external_id),
        "external_etag": item.get("lastModifiedDateTime") or item.get("@odata.etag") or "",
    }


async def create_remote_task(
    title: str,
    *,
    notes: str | None = None,
    due_at: str | None = None,
    reminder_at: str | None = None,
    priority: str | None = None,
    important: bool = False,
    list_id: str | None = None,
    categories: list[str] | None = None,
    connection: Any | None = None,
) -> dict[str, str] | None:
    """Create this task in Microsoft To Do, if To Do is connected.

    Returns the identity to mirror locally, or None when there is no connector
    to write to -- which is the ordinary case on a machine that has not added
    one, and not an error.

    `connection` is for a caller that already holds one -- the push half does.
    Reaching for the published manager when the caller was handed a different
    one is how a sync run against an explicit manager silently created nothing.

    A task made for today is created *in* the My Day list -- the caller passes
    that list's id -- rather than created anywhere and marked afterwards. There
    is nothing to mark: My Day is which list the task is in.
    """
    from psok.mcp import live

    connection = connection or live.connection(SERVER)
    if connection is None:
        return None

    target = list_id or await default_list_id(connection)
    if not target:
        raise SyncUnavailable("Microsoft To Do returned no lists to put a task in")

    arguments = {
        "listId": target,
        "title": title,
        **_task_arguments(
            notes=notes,
            due_at=due_at,
            reminder_at=reminder_at,
            priority=priority,
            important=important,
            categories=categories,
        ),
    }
    return _identity(await _call_json(connection, "create_task", arguments), what="task")


async def move_remote_task(
    row: Any,
    *,
    to_list: str,
    from_list: str,
    connection: Any | None = None,
) -> dict[str, str] | None:
    """Move a task between To Do lists, and hand back its new identity.

    **Graph has no move.** A `todoTask` belongs to the list in its URL, and
    `PATCH .../lists/{a}/tasks/{id}` cannot rename that; there is no endpoint
    that takes a destination. So a move is a create in the target followed by a
    delete from the source, which has three consequences worth stating rather
    than discovering:

    - **The task gets a new id.** Every local mirror of it is repointed here;
      anything holding the old id -- a link someone saved, an open To Do screen
      -- is holding a task that no longer exists.
    - **Only the fields sent survive.** Checklist items, attachments and the
      creation date do not come along, because Graph will not accept them on a
      create. Title, notes, dates, importance, status and tags do.
    - **The order is create-then-delete, never the reverse.** If the delete
      fails the user has the task twice, which they can see and fix; if the
      create failed after a delete they would have lost it.

    Returns None when nothing is connected, matching `create_remote_task`.
    """
    from psok.mcp import live

    connection = connection or live.connection(SERVER)
    if connection is None:
        return None

    created = await create_remote_task(
        row["title"],
        notes=row["notes"],
        due_at=row["due_at"],
        reminder_at=row["reminder_at"],
        priority=row["priority"],
        important=bool(row["important"]),
        list_id=to_list,
        categories=_categories_for(row),
        connection=connection,
    )
    if created is None:
        return None
    # The status has to be a second call: `create_task` takes `status`, but a
    # task created `completed` comes back with no completion date, and the
    # column PSOK shows "done today" from would be empty.
    if row["status"] and row["status"] != "todo":
        await _call_json(
            connection,
            "update_task",
            {
                "listId": to_list,
                "taskId": created["external_id"],
                **_task_arguments(status=row["status"]),
            },
        )
    await connection.call(
        "delete_task", {"listId": from_list, "taskId": str(row["external_id"])}
    )
    return created


async def _call_json(connection: Any, tool: str, arguments: dict) -> Any:
    return _payload(await connection.call(tool, arguments))


async def sync(manager: Any) -> SyncReport:
    """Push local changes, then pull everything back. Raises SyncUnavailable if it cannot."""
    connection = getattr(manager, "connections", {}).get(SERVER) if manager else None
    if connection is None or not connection.connected:
        raise SyncUnavailable(
            f"the '{SERVER}' connector is not running. Switch it on and sign in first."
        )

    report = SyncReport()
    repository = TaskRepository()
    list_repository = TaskListRepository()

    try:
        raw_lists = await _paged(connection, "list_task_lists", {}, "lists", "taskLists")
    except TruncatedListing as exc:
        raise SyncUnavailable(
            "Microsoft To Do returned an incomplete list of lists; not syncing against"
            " a partial answer."
        ) from exc
    if not raw_lists:
        raise SyncUnavailable(
            "Microsoft To Do returned no task lists. That usually means the connector"
            " is not signed in yet -- open it and press Connect."
        )
    report.lists = len(raw_lists)
    by_external = _sync_lists(list_repository, report, raw_lists)

    # Push first: see the module docstring. Anything that fails keeps its
    # `dirty_at` and is retried next tick rather than stopping the pull.
    await _push(connection, repository, list_repository, report)

    # The lists are fetched together and applied afterwards, in order. Serially
    # this was one round trip per list end to end -- four lists, four waits,
    # every ninety seconds -- and the calls have nothing to say to each other:
    # each names its own list and the answers are independent. Applying them
    # afterwards rather than as they land keeps the pull single-threaded where
    # it touches SQLite, and keeps `report` counting in list order.
    targets = [task_list for task_list in raw_lists if task_list.get("id")]
    answers = await asyncio.gather(
        *(
            _paged(
                connection,
                "list_tasks",
                {"listId": task_list["id"], "status": "all"},
                "tasks",
            )
            for task_list in targets
        ),
        return_exceptions=True,
    )

    seen: set[str] = set()
    truncated = False
    for task_list, items in zip(targets, answers, strict=True):
        if isinstance(items, TruncatedListing):
            truncated = True
            continue
        if isinstance(items, BaseException):
            raise items
        local_list = by_external.get(str(task_list["id"]))
        for item in items:
            external_id = item.get("id")
            if not external_id:
                continue
            seen.add(str(external_id))
            _apply(repository, report, local_list, item)

    if truncated:
        # Some list came back short. Retiring on that would cancel tasks that
        # exist; the pull's other work still stands.
        log.warning("skipping retirement this pass: a listing was incomplete")
    else:
        _retire_missing(repository, report, seen)
    return report


def _sync_lists(
    repository: TaskListRepository, report: SyncReport, raw_lists: list[dict]
) -> dict[str, int]:
    """Mirror To Do's lists, and hand back Graph id -> local id.

    This is the line the whole feature turned on. `_apply` used to take the list
    it belonged to and never look at it, so every task in every list collapsed
    into one flat set and every task PSOK created went to the default list.
    """
    mapping: dict[str, int] = {}
    seen: set[str] = set()
    for position, task_list in enumerate(raw_lists):
        external_id = task_list.get("id")
        if not external_id:
            continue
        external_id = str(external_id)
        seen.add(external_id)
        name = (task_list.get("displayName") or "").strip() or "(untitled list)"
        is_default = task_list.get("wellknownListName") == "defaultList"

        existing = repository.by_external(SOURCE, external_id)
        if existing is None:
            # A list created locally while nothing was signed in is adopted
            # rather than duplicated -- otherwise signing in gives the user two
            # "Groceries", one of which never reaches their phone.
            orphan = repository.by_name(name)
            if orphan is not None and orphan["external_id"] is None:
                repository.update(
                    orphan["id"],
                    external_source=SOURCE,
                    external_id=external_id,
                    is_default=1 if is_default else 0,
                    position=position,
                )
                mapping[external_id] = orphan["id"]
                continue
            mapping[external_id] = repository.create(
                name,
                external_source=SOURCE,
                external_id=external_id,
                is_default=is_default,
                position=position,
            )
            report.lists_created += 1
            continue

        mapping[external_id] = existing["id"]
        changed: dict[str, Any] = {}
        if existing["name"] != name:
            changed["name"] = name
        if bool(existing["is_default"]) != is_default:
            changed["is_default"] = 1 if is_default else 0
        if existing["position"] != position:
            changed["position"] = position
        if existing["retired_at"]:
            changed["retired_at"] = None
        if changed:
            repository.update(existing["id"], **changed)

    for row in repository.external_rows(SOURCE):
        if str(row["external_id"]) not in seen:
            repository.retire(row["id"])
            report.lists_retired += 1
    return mapping


async def _push(
    connection: Any,
    repository: TaskRepository,
    list_repository: TaskListRepository,
    report: SyncReport,
) -> None:
    """Send local changes upstream: updates for known rows, creates for new ones."""
    for row in repository.dirty(SOURCE):
        list_external = _list_external_id(list_repository, row["list_id"])
        if not list_external:
            continue
        arguments = {
            "listId": list_external,
            "taskId": row["external_id"],
            **_task_arguments(
                title=row["title"],
                notes=row["notes"],
                due_at=row["due_at"],
                reminder_at=row["reminder_at"],
                priority=row["priority"],
                important=bool(row["important"]),
                status=row["status"],
                categories=_categories_for(row),
            ),
        }
        try:
            await _call_json(connection, "update_task", arguments)
        except Exception as exc:
            # Left dirty on purpose: the next tick tries again, and one
            # unwritable task must not stop every other task from syncing.
            log.info("could not push task %s to Microsoft To Do: %s", row["id"], exc)
            continue
        repository.update(row["id"], dirty_at=None, last_synced_at=_now())
        report.pushed += 1

    unsynced = repository.unsynced()
    if not unsynced:
        return
    # Creating upstream is at-least-once: the Graph call can succeed and the
    # local adopt fail (a crash, a rolled-back write), and the next tick then
    # creates a second copy of the same task in the user's account. Graph offers
    # no idempotency key, so the guard is to look before leaping -- one listing
    # per target list, only when there is something to create.
    claimed = {str(r["external_id"]) for r in repository.external_ids(SOURCE) if r["external_id"]}
    existing: dict[str, dict[str, str]] = {}
    for list_external in {_list_external_id(list_repository, r["list_id"]) for r in unsynced}:
        if not list_external:
            continue
        found: dict[str, str] = {}
        for item in await _paged(
            connection, "list_tasks", {"listId": list_external, "status": "all"}, "tasks"
        ):
            title = (item.get("title") or "").strip()
            item_id = str(item.get("id") or "")
            # Only an unclaimed one: two local rows with the same title must not
            # both adopt the same upstream task.
            if title and item_id and item_id not in claimed:
                found.setdefault(title, item_id)
        existing[list_external] = found

    for row in unsynced:
        list_external = _list_external_id(list_repository, row["list_id"])
        match = existing.get(list_external or "", {}).pop(row["title"].strip(), None)
        if match:
            log.info(
                "task %s already exists in Microsoft To Do; adopting it rather than"
                " creating a second copy",
                row["id"],
            )
            repository.adopt_external(
                row["id"], source=SOURCE, external_id=match, external_etag=None
            )
            claimed.add(match)
            continue
        try:
            external = await create_remote_task(
                row["title"],
                notes=row["notes"],
                due_at=row["due_at"],
                reminder_at=row["reminder_at"],
                priority=row["priority"],
                important=bool(row["important"]),
                list_id=list_external,
                connection=connection,
            )
        except Exception as exc:
            log.info("could not create task %s in Microsoft To Do: %s", row["id"], exc)
            continue
        if external is None:
            return  # nothing signed in; the rest will fail the same way
        repository.adopt_external(
            row["id"],
            source=SOURCE,
            external_id=external["external_id"],
            external_etag=external.get("external_etag") or None,
        )
        report.pushed += 1


def _list_external_id(repository: TaskListRepository, list_id: int | None) -> str | None:
    if list_id is None:
        row = repository.default()
    else:
        row = repository.get(list_id)
    return str(row["external_id"]) if row is not None and row["external_id"] else None


def _apply(
    repository: TaskRepository,
    report: SyncReport,
    local_list: int | None,
    item: dict,
) -> None:
    external_id = str(item["id"])
    title = (item.get("title") or "").strip() or "(untitled)"
    body = item.get("body")
    notes = body.get("content") if isinstance(body, dict) else body
    importance = str(item.get("importance") or "")

    # Every tag the task carries, kept verbatim so the next push sends them back
    # rather than replacing them with a shorter list. None of them mean anything
    # to PSOK: My Day is `list_id`, decided by the list this task came out of.
    remote_categories = [c for c in (item.get("categories") or []) if isinstance(c, str)]

    existing = repository.by_external(SOURCE, external_id)

    fields = {
        "title": title,
        "notes": (notes or None),
        "status": STATUS.get(str(item.get("status") or ""), "todo"),
        "due_at": _timestamp(item.get("dueDateTime")),
        "reminder_at": _timestamp(item.get("reminderDateTime")),
        # Dropped entirely until 2026-08-28. To Do knew three tasks were
        # finished today and PSOK recorded the completion time of one, so
        # "what did I get done today" could not be answered from local data.
        "completed_at": _completed_at(item, existing),
        "priority": PRIORITY.get(importance),
        "important": 1 if importance == "high" else 0,
        "list_id": local_list,
        "external_etag": item.get("lastModifiedDateTime") or item.get("@odata.etag"),
        "external_categories": json.dumps(remote_categories),
    }

    if existing is None:
        repository.create(
            title,
            notes=fields["notes"],
            due_at=fields["due_at"],
            priority=fields["priority"],
            source="sync",
            reminder_at=fields["reminder_at"],
            external_source=SOURCE,
            external_id=external_id,
            external_etag=fields["external_etag"],
            completed_at=fields["completed_at"],
            list_id=local_list,
            important=bool(fields["important"]),
            status=fields["status"],
            external_categories=fields["external_categories"],
        )
        report.created += 1
        return

    changed = {k: v for k, v in fields.items() if existing[k] != v}

    if not changed:
        repository.update(existing["id"], last_synced_at=_now())
        return

    # Only when the time it is owed at actually moved. Re-announcing a reminder
    # because a title was corrected would be noise.
    if "due_at" in changed or "reminder_at" in changed:
        changed["reminded_at"] = None
    changed["last_synced_at"] = _now()
    # The push already ran, so upstream holds whatever was local. Anything
    # arriving now is newer than the local edit and supersedes it.
    changed["dirty_at"] = None
    repository.update(existing["id"], **changed)
    report.updated += 1


def _retire_missing(repository: TaskRepository, report: SyncReport, seen: set[str]) -> None:
    """Close out rows To Do no longer has, without deleting them.

    Only ever reached when the pull returned lists -- `sync` raises before this
    if it did not -- so an outage cannot be mistaken for an emptied account.
    """
    for row in repository.external_ids(SOURCE):
        if str(row["external_id"]) in seen or row["status"] in ("done", "cancelled"):
            continue
        repository.update(row["id"], status="cancelled", last_synced_at=_now())
        report.cancelled += 1


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")

