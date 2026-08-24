"""Mirror Microsoft To Do into the local task store.

**One way, on purpose.** To Do is the source of truth for anything that came
from To Do; PSOK's copy exists so `due_at` and `reminder_at` are readable by the
reminder loop, and so a task can be cross-referenced against the notes vault
without a network round trip. Local edits stay local: pushing them back needs
conflict resolution and change tracking, and shipping half of that is how a sync
loses someone's data.

Three properties this depends on, each load-bearing:

- **Identity, not position.** Rows are keyed on `(external_source,
  external_id)` behind a unique index, so pulling twice updates one row rather
  than making two. The mutation check for this is to drop the index and watch
  the duplicate appear.
- **Local fields are never overwritten.** `scheduled_at` and a note typed in
  PSOK have no counterpart in To Do; a pull that wrote every column would erase
  them on every tick.
- **A task that vanishes is cancelled, not deleted.** An empty or partial
  response is indistinguishable from an emptied account, and deleting rows on
  the strength of one is unrecoverable.

The connector is reached through the live registry's manager, so this uses the
process that is already running and the account already signed in -- not a
second subprocess and not a second sign-in.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psok.db.repositories import TaskRepository

log = logging.getLogger(__name__)

SERVER = "microsoft-todo"
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


class SyncUnavailable(RuntimeError):
    """The connector is not running or not signed in. Not an error to retry hard."""


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    cancelled: int = 0
    lists: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "cancelled": self.cancelled,
            "lists": self.lists,
        }

    def summary(self) -> str:
        if not (self.created or self.updated or self.cancelled):
            return f"already up to date with Microsoft To Do ({self.lists} lists)"
        parts = []
        if self.created:
            parts.append(f"{self.created} new")
        if self.updated:
            parts.append(f"{self.updated} updated")
        if self.cancelled:
            parts.append(f"{self.cancelled} gone from To Do")
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


async def sync(manager: Any) -> SyncReport:
    """Pull every To Do list into `tasks`. Raises SyncUnavailable if it cannot."""
    connection = getattr(manager, "connections", {}).get(SERVER) if manager else None
    if connection is None or not connection.connected:
        raise SyncUnavailable(
            f"the '{SERVER}' connector is not running. Switch it on and sign in first."
        )

    report = SyncReport()
    repository = TaskRepository()
    seen: set[str] = set()

    lists = _items(_payload(await connection.call("list_task_lists", {})), "lists", "taskLists")
    if not lists:
        raise SyncUnavailable(
            "Microsoft To Do returned no task lists. That usually means the connector"
            " is not signed in yet -- open it and press Connect."
        )
    report.lists = len(lists)

    for task_list in lists:
        list_id = task_list.get("id")
        if not list_id:
            continue
        payload = _payload(
            await connection.call("list_tasks", {"listId": list_id, "status": "all"})
        )
        for item in _items(payload, "tasks"):
            external_id = item.get("id")
            if not external_id:
                continue
            seen.add(str(external_id))
            _apply(repository, report, task_list, item)

    _retire_missing(repository, report, seen)
    return report


def _apply(repository: TaskRepository, report: SyncReport, task_list: dict, item: dict) -> None:
    external_id = str(item["id"])
    title = (item.get("title") or "").strip() or "(untitled)"
    body = item.get("body")
    notes = body.get("content") if isinstance(body, dict) else body
    fields = {
        "title": title,
        "status": STATUS.get(str(item.get("status") or ""), "todo"),
        "due_at": _timestamp(item.get("dueDateTime")),
        "reminder_at": _timestamp(item.get("reminderDateTime")),
        "priority": PRIORITY.get(str(item.get("importance") or "")),
        "external_etag": item.get("lastModifiedDateTime") or item.get("@odata.etag"),
    }

    existing = repository.by_external(SOURCE, external_id)
    if existing is None:
        repository.create(
            title,
            notes=(notes or None),
            due_at=fields["due_at"],
            priority=fields["priority"],
            source="sync",
            reminder_at=fields["reminder_at"],
            external_source=SOURCE,
            external_id=external_id,
            external_etag=fields["external_etag"],
        )
        if fields["status"] != "todo":
            row = repository.by_external(SOURCE, external_id)
            if row is not None:
                repository.update(row["id"], status=fields["status"])
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
