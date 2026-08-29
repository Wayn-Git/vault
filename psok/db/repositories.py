"""Repository layer. Nothing above this module issues SQL directly.

Split by domain from the start rather than accumulating into one file, which is
the one thing Khoj's otherwise-good adapters layer got wrong.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psok.db.connection import get_connection


def _conn(conn: sqlite3.Connection | None) -> sqlite3.Connection:
    return conn or get_connection()


def _now() -> str:
    """Local naive, to the second.

    Every timestamp in this schema is local naive and compared as a string by
    SQLite. A UTC value on one side of such a comparison is off by the machine's
    offset and fails silently -- which is how reminders once arrived late by
    five and a half hours.
    """
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _today() -> str:
    """Local calendar date. "Today" is the one the user's clock shows.

    Not `date('now')`. SQLite's is UTC, and every timestamp compared against it
    here is local -- so for the machine's offset either side of midnight the two
    disagreed and the day's buckets emptied themselves. East of Greenwich that
    window is the small hours; west of it, the evening.
    """
    return datetime.now().date().isoformat()


def _fold_list_name(name: str | None) -> str:
    """A list name reduced to what a person would actually type.

    Leading emoji, symbols and punctuation go; case goes; surrounding space
    goes. Only *leading* decoration is stripped, so "Q1 2026" keeps its digits
    and "College 2026" still differs from "College Admin".
    """
    text = (name or "").strip()
    while text and not text[0].isalnum():
        text = text[1:].lstrip()
    return text.casefold()


#: The To Do list that *is* My Day.
#:
#: My Day is not a flag on a task and not a tag: it is one list, kept in
#: Microsoft To Do beside the others, which both PSOK and the phone open. That
#: is the only arrangement where the same tasks appear in both places without a
#: gesture unique to one of them -- To Do's own My Day is an overlay its API
#: does not expose (see `psok/sync/microsoft_todo.py`), so anything built on it
#: is invisible from here.
#:
#: Matched by name, folded the same way every other list name is, so "🌞 My Day"
#: answers to it. "Today" is accepted because it is the other name people give
#: the same list.
MY_DAY_LIST_NAMES = ("my day", "today")


def is_my_day_list(name: str | None) -> bool:
    return _fold_list_name(name) in MY_DAY_LIST_NAMES


# --------------------------------------------------------------------------
# conversations + messages
# --------------------------------------------------------------------------


@dataclass
class Message:
    id: int
    role: str
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: bool = False
    pinned: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Message:
        keys = row.keys()
        return cls(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            tool_calls=json.loads(row["tool_calls"]) if row["tool_calls"] else None,
            tool_call_id=row["tool_call_id"],
            tool_name=row["tool_name"],
            is_error=bool(row["is_error"]),
            # Read defensively: a row selected before the column existed, or by
            # a query that does not ask for it, is not a reason to raise.
            pinned=bool(row["pinned"]) if "pinned" in keys else False,
        )


class ConversationRepository:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = _conn(conn)

    def create(
        self,
        provider: str,
        model: str,
        title: str | None = None,
        automation_id: str | None = None,
    ) -> str:
        cid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO conversations (id, title, provider, model, automation_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (cid, title, provider, model, automation_id),
        )
        self.conn.commit()
        return cid

    def get(self, conversation_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()

    def list(self, limit: int = 50, *, include_automations: bool = False) -> list[sqlite3.Row]:
        """Conversations, newest first. Scheduled runs are excluded by default.

        They share this list's fixed limit, and a pair of automations on a
        15-minute interval writes roughly 192 a day -- enough to push every
        conversation a person actually had off the end of it. They are listed
        per automation instead, by `runs_of`.
        """
        if include_automations:
            return self.conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM conversations WHERE automation_id IS NULL"
            " ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def runs_of(self, automation_id: str, limit: int = 50) -> list[sqlite3.Row]:
        """Every conversation one automation has written, newest first."""
        return self.conn.execute(
            "SELECT * FROM conversations WHERE automation_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (automation_id, limit),
        ).fetchall()

    def prune_runs(self, automation_id: str, keep: int) -> int:
        """Drop all but the newest `keep` runs of one automation.

        Nothing pruned these before, so they accumulated for as long as the
        automation was enabled. Comparing a failed run against the one before it
        is the usual reason to look, so a handful are kept rather than one.
        """
        stale = self.conn.execute(
            "SELECT id FROM conversations WHERE automation_id = ?"
            " ORDER BY created_at DESC LIMIT -1 OFFSET ?",
            (automation_id, keep),
        ).fetchall()
        for row in stale:
            self.delete(row["id"])
        return len(stale)

    def update(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        fallback: list[str] | None = None,
    ) -> bool:
        """Change the conversation's title, its provider/model pair, or its chain.

        Provider and model are plain strings the loop re-resolves on every turn,
        so switching model mid-conversation is this write and nothing else
        (ai-runtime.md, "Switching models").

        `fallback` is stored as JSON. An empty list is meaningful and different
        from None -- it means "do not fall back at all for this conversation" --
        so it is written rather than treated as absent.
        """
        fields: dict[str, Any] = {"title": title, "provider": provider, "model": model}
        if fallback is not None:
            fields["fallback"] = json.dumps(fallback)
        updates = {k: v for k, v in fields.items() if v is not None}
        if not updates:
            return self.get(conversation_id) is not None

        assignments = ", ".join(f"{k} = ?" for k in updates)
        cursor = self.conn.execute(
            f"UPDATE conversations SET {assignments}, updated_at = datetime('now')"
            " WHERE id = ?",
            (*updates.values(), conversation_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete(self, conversation_id: str) -> bool:
        """Remove a conversation and everything scoped to it.

        Messages cascade through the foreign key, but two tables key on the
        conversation id as a plain scope string rather than a reference --
        capability_state and memory_state -- so a deleted conversation would
        otherwise leave rows nothing can ever reach again. Extracted memories
        are deliberately kept: a fact learned in a conversation outlives it,
        which is why memories.conversation_id is not a foreign key.
        """
        cursor = self.conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        if cursor.rowcount:
            self.conn.execute(
                "DELETE FROM capability_state WHERE scope = ?", (conversation_id,)
            )
            self.conn.execute(
                "DELETE FROM memory_state WHERE scope = ?", (conversation_id,)
            )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_all(self, *, include_automations: bool = False) -> int:
        """Delete every conversation, one at a time. Returns how many went.

        Row by row rather than one `DELETE FROM conversations`, because the
        scoped rows in `capability_state` and `memory_state` key on the id as a
        plain string and no foreign key will take them with it. A bulk statement
        would leave those behind for every conversation at once -- the same leak
        `delete` exists to prevent, multiplied.

        Automation runs are excluded by default for the same reason they are
        excluded from the rail: they are the record of what a rule did, not a
        conversation anyone had, and they are already pruned per automation.
        """
        sql = "SELECT id FROM conversations"
        if not include_automations:
            sql += " WHERE automation_id IS NULL"
        rows = self.conn.execute(sql).fetchall()
        return sum(1 for row in rows if self.delete(row["id"]))

    def touch(self, conversation_id: str) -> None:
        self.conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        self.conn.commit()


class MessageRepository:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = _conn(conn)

    def append(
        self,
        conversation_id: str,
        role: str,
        content: str | None = None,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        is_error: bool = False,
        token_count: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages (conversation_id, role, content, tool_calls, tool_call_id,"
            " tool_name, is_error, token_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                tool_call_id,
                tool_name,
                int(is_error),
                token_count,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_pinned(self, conversation_id: str, message_id: int, pinned: bool) -> bool:
        """Pin or unpin one message.

        Scoped by conversation as well as by id so a pin cannot be applied to a
        message in a conversation the caller did not name -- message ids are
        global integers, and an interface that has the wrong one open would
        otherwise silently pin somebody else's turn.
        """
        cursor = self.conn.execute(
            "UPDATE messages SET pinned = ? WHERE id = ? AND conversation_id = ?",
            (int(pinned), message_id, conversation_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def pinned(self, conversation_id: str) -> list[Message]:
        return [
            Message.from_row(r)
            for r in self.conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? AND pinned = 1 ORDER BY id",
                (conversation_id,),
            )
        ]

    def history(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        sql = "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id"
        params: tuple = (conversation_id,)
        if limit:
            # newest N, returned oldest-first
            sql = (
                "SELECT * FROM (SELECT * FROM messages WHERE conversation_id = ?"
                " ORDER BY id DESC LIMIT ?) ORDER BY id"
            )
            params = (conversation_id, limit)
        return [Message.from_row(r) for r in self.conn.execute(sql, params).fetchall()]


# --------------------------------------------------------------------------
# permissions + audit
# --------------------------------------------------------------------------


class ConfirmationPreferenceRepository:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = _conn(conn)

    def get(self, operation_key: str) -> str | None:
        row = self.conn.execute(
            "SELECT decision FROM confirmation_preferences WHERE operation_key = ?",
            (operation_key,),
        ).fetchone()
        return row["decision"] if row else None

    def list(self) -> list[sqlite3.Row]:
        """Every standing decision, newest first.

        "Don't ask again" is a grant the user made once and then cannot see;
        without a way to read it back there is no way to notice a tool that
        stopped asking, and no way to take it back.
        """
        return self.conn.execute(
            "SELECT operation_key, decision, risk_level, created_at"
            " FROM confirmation_preferences ORDER BY created_at DESC"
        ).fetchall()

    def remember(self, operation_key: str, decision: str, risk_level: str) -> None:
        self.conn.execute(
            "INSERT INTO confirmation_preferences (operation_key, decision, risk_level)"
            " VALUES (?, ?, ?) ON CONFLICT(operation_key) DO UPDATE SET"
            " decision = excluded.decision, risk_level = excluded.risk_level",
            (operation_key, decision, risk_level),
        )
        self.conn.commit()

    def clear(self, operation_key: str | None = None) -> None:
        if operation_key:
            self.conn.execute(
                "DELETE FROM confirmation_preferences WHERE operation_key = ?", (operation_key,)
            )
        else:
            self.conn.execute("DELETE FROM confirmation_preferences")
        self.conn.commit()


class ExecutionLogRepository:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = _conn(conn)

    def record(
        self,
        *,
        tool_name: str,
        tool_source: str,
        conversation_id: str | None = None,
        message_id: int | None = None,
        arguments: dict[str, Any] | None = None,
        result_summary: str | None = None,
        error: str | None = None,
        risk_level: str | None = None,
        confirmation_decision: str | None = None,
        duration_ms: int | None = None,
    ) -> int:
        from psok.secrets import redact

        cur = self.conn.execute(
            "INSERT INTO execution_logs (conversation_id, message_id, tool_name, tool_source,"
            " arguments, result_summary, error, risk_level, confirmation_decision, duration_ms)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                message_id,
                tool_name,
                tool_source,
                json.dumps(redact(arguments)) if arguments is not None else None,
                result_summary[:2000] if result_summary else None,
                error,
                risk_level,
                confirmation_decision,
                duration_ms,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def recent(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM execution_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


class McpTrustRepository:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = _conn(conn)

    def is_trusted(self, server_name: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM mcp_trusted_servers WHERE server_name = ?", (server_name,)
            ).fetchone()
            is not None
        )

    def trust(self, server_name: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO mcp_trusted_servers (server_name) VALUES (?)", (server_name,)
        )
        self.conn.commit()


# --------------------------------------------------------------------------
# tasks + calendar
# --------------------------------------------------------------------------


class TaskRepository:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = _conn(conn)

    def create(
        self,
        title: str,
        *,
        notes: str | None = None,
        due_at: str | None = None,
        scheduled_at: str | None = None,
        duration_estimate_minutes: int | None = None,
        priority: str | None = None,
        source: str = "user",
        reminder_at: str | None = None,
        external_source: str | None = None,
        external_id: str | None = None,
        external_etag: str | None = None,
        list_id: int | None = None,
        important: bool = False,
        external_categories: str | None = None,
        completed_at: str | None = None,
        status: str | None = None,
        dirty_at: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO tasks (title, notes, due_at, scheduled_at, duration_estimate_minutes,"
            " priority, source, reminder_at, external_source, external_id, external_etag,"
            " list_id, important, external_categories, completed_at, dirty_at,"
            " status, last_synced_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 'todo'),"
            " CASE WHEN ? IS NULL THEN NULL ELSE datetime('now') END)",
            (
                title,
                notes,
                due_at,
                scheduled_at,
                duration_estimate_minutes,
                priority,
                source,
                reminder_at,
                external_source,
                external_id,
                external_etag,
                list_id,
                1 if important else 0,
                external_categories,
                completed_at,
                dirty_at,
                status,
                external_id,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get(self, task_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    def update(self, task_id: int, **fields: Any) -> None:
        allowed = {
            "title",
            "notes",
            "due_at",
            "scheduled_at",
            "duration_estimate_minutes",
            "status",
            "priority",
            "calendar_event_id",
            "reminder_at",
            "reminded_at",
            "external_etag",
            "last_synced_at",
            "list_id",
            "important",
            "external_categories",
            "completed_at",
            "dirty_at",
        }
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        # `completed_at` is a fact about the status, not a field a caller should
        # have to remember to pass -- and one that has to be cleared when a task
        # is reopened, or a re-completed task keeps the first date.
        if "status" in sets and "completed_at" not in sets:
            sets["completed_at"] = _now() if sets["status"] == "done" else None
        clause = ", ".join(f"{k} = ?" for k in sets)
        self.conn.execute(
            f"UPDATE tasks SET {clause}, updated_at = datetime('now') WHERE id = ?",
            (*sets.values(), task_id),
        )
        self.conn.commit()

    def upcoming(self, limit: int = 20, include_done: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM tasks"
        if not include_done:
            sql += " WHERE status IN ('todo', 'in_progress')"
        sql += " ORDER BY (due_at IS NULL), due_at, id LIMIT ?"
        return self.conn.execute(sql, (limit,)).fetchall()

    def due_reminders(self, now: str) -> list[sqlite3.Row]:
        """Open tasks whose reminder has come round and has not been given.

        `reminder_at` when it is set, otherwise `due_at` -- so a plain deadline
        is announced without anyone having to set a second field, and a task
        with neither is never announced at all.
        """
        return self.conn.execute(
            "SELECT * FROM tasks"
            " WHERE status IN ('todo', 'in_progress')"
            "   AND reminded_at IS NULL"
            "   AND COALESCE(reminder_at, due_at) IS NOT NULL"
            "   AND COALESCE(reminder_at, due_at) <= ?"
            " ORDER BY COALESCE(reminder_at, due_at), id",
            (now,),
        ).fetchall()

    def mark_reminded(self, task_id: int, when: str) -> bool:
        """Claim a reminder. False if something already claimed it.

        The `reminded_at IS NULL` predicate is the claim: two ticks overlapping,
        or a tick racing a restart, cannot both win it, so nobody is told twice.
        """
        cur = self.conn.execute(
            "UPDATE tasks SET reminded_at = ?, updated_at = datetime('now')"
            " WHERE id = ? AND reminded_at IS NULL",
            (when, task_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def by_external(self, source: str, external_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE external_source = ? AND external_id = ?",
            (source, external_id),
        ).fetchone()

    def external_ids(self, source: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, external_id, status FROM tasks WHERE external_source = ?",
            (source,),
        ).fetchall()

    # ---------------------------------------------------------------- buckets
    #
    # The five views the Tasks page is made of. They live here rather than in
    # the view because the counts and the rows have to agree: a sidebar saying
    # "Missed 5" over a list showing four is worse than no count at all, and the
    # only way to guarantee they match is one predicate, used twice.
    #
    # Missed is computed, never stored. A stored "missed" flag needs a job to
    # set it, a rule for unsetting it, and a migration for rows that predate
    # both -- and it is wrong for exactly as long as that job is not running.

    OPEN = "status IN ('todo', 'in_progress')"

    # Today is bound in as `:today` rather than written as `date('now')`.
    # SQLite's `now` is UTC; every column these compare against holds local
    # naive time. The two agree for most of the day and disagree either side of
    # midnight by the machine's offset -- at UTC+5:30 that is 00:00 to 05:30
    # local, during which My Day read empty, the sun did nothing visible, and
    # Missed forgot the previous evening's deadlines. Nothing announced it,
    # because there is no error in comparing two well-formed dates.

    #: My Day is the contents of one list, and nothing else.
    #:
    #: It used to be a date stamp (`my_day_on`) fed by three different gestures
    #: -- a sun in PSOK writing a "My Day" category, a `#myday` hashtag, and a
    #: list of this name -- which meant the page could disagree with the phone
    #: about what was in today, and usually did: tasks added through To Do's own
    #: My Day carry none of the three, because that overlay is not in its API.
    #: One list is the only version both ends can see. Cancelled rows are the
    #: tasks a pull no longer found upstream, so they are not in the list any
    #: more either.
    _MY_DAY = "list_id = :my_day_list AND status != 'cancelled'"
    _MISSED = "due_at IS NOT NULL AND due_at < :today"
    _IMPORTANT = "important = 1"
    #: Everything nobody has scheduled or claimed for today. `:my_day_list` is
    #: null when no such list exists, and `IS NOT` against null would then hide
    #: every unfiled task, so the comparison is guarded rather than written bare.
    _GENERAL = (
        "due_at IS NULL AND scheduled_at IS NULL"
        " AND (:my_day_list IS NULL OR list_id IS NOT :my_day_list)"
    )

    def my_day_list_id(self) -> int | None:
        """The local id of the list that is My Day, or None if there is none.

        Read on every bucket query rather than cached: the list can arrive from
        a sync at any moment, and a stale cache would leave My Day empty until
        a restart with nothing on screen explaining why.
        """
        for row in self.conn.execute(
            "SELECT id, name FROM task_lists WHERE retired_at IS NULL ORDER BY position, id"
        ):
            if is_my_day_list(row["name"]):
                return int(row["id"])
        return None

    def _bucket_where(self, bucket: str, list_id: int | None = None) -> tuple[str, dict]:
        params = {
            "today": _today(),
            "list_id": list_id,
            "my_day_list": self.my_day_list_id(),
        }
        if bucket == "my_day":
            return self._MY_DAY, params
        if bucket == "missed":
            return f"{self.OPEN} AND {self._MISSED}", params
        if bucket == "important":
            return f"{self.OPEN} AND {self._IMPORTANT}", params
        if bucket == "general":
            return f"{self.OPEN} AND {self._GENERAL}", params
        if bucket == "completed":
            # Cancelled is not completed. `upcoming(include_done=True)` conflates
            # them, which made "Showing done" quietly mean "showing everything
            # including things you gave up on".
            return "status = 'done'", params
        if bucket == "list":
            return f"{self.OPEN} AND list_id IS :list_id", params
        if bucket == "all":
            return self.OPEN, params
        raise ValueError(f"unknown task bucket '{bucket}'")

    #: Overdue first, then by deadline, then undated. `id` last so the order is
    #: total -- without it two tasks due the same minute swap places between
    #: reads and the list appears to shuffle itself.
    _ORDER = "ORDER BY important DESC, (due_at IS NULL), due_at, id"

    #: My Day mixes open work with what was finished today, and the two are not
    #: peers: the open ones are the list, the done ones are the record. Sorting
    #: them together buried a task still to do underneath three that were
    #: already crossed off. Done sinks; the rest keeps the usual order.
    _MY_DAY_ORDER = (
        "ORDER BY (status = 'done'), important DESC, (due_at IS NULL), due_at, id"
    )

    def bucket(
        self, name: str, *, list_id: int | None = None, limit: int = 200
    ) -> list[sqlite3.Row]:
        where, params = self._bucket_where(name, list_id)
        if name == "completed":
            order = "ORDER BY completed_at DESC, id DESC"
        elif name == "my_day":
            order = self._MY_DAY_ORDER
        else:
            order = self._ORDER
        return self.conn.execute(
            f"SELECT * FROM tasks WHERE {where} {order} LIMIT :limit", {**params, "limit": limit}
        ).fetchall()

    def counts(self) -> dict[str, int]:
        """Every bucket count in one pass, plus one per list.

        One query per bucket would be six round trips for a sidebar that redraws
        on every mutation.
        """
        out: dict[str, int] = {}
        for name in ("my_day", "missed", "important", "general", "completed", "all"):
            where, params = self._bucket_where(name)
            row = self.conn.execute(
                f"SELECT count(*) FROM tasks WHERE {where}", params
            ).fetchone()
            out[name] = row[0]
        for row in self.conn.execute(
            f"SELECT list_id, count(*) AS n FROM tasks WHERE {self.OPEN} GROUP BY list_id"
        ):
            out[f"list:{row['list_id']}"] = row["n"]
        return out

    def dirty(self, source: str, limit: int = 200) -> list[sqlite3.Row]:
        """Rows changed locally since they last reached the connector."""
        return self.conn.execute(
            "SELECT * FROM tasks WHERE dirty_at IS NOT NULL AND external_source = ?"
            " ORDER BY dirty_at LIMIT ?",
            (source, limit),
        ).fetchall()

    def unsynced(self, limit: int = 200) -> list[sqlite3.Row]:
        """Local rows that never reached the connector at all.

        Created while nothing was signed in, or while the upstream write failed.
        They are the other half of the push: `dirty` updates what exists there,
        this creates what does not.
        """
        return self.conn.execute(
            f"SELECT * FROM tasks WHERE external_id IS NULL AND {self.OPEN}"
            " ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()

    def adopt_external(
        self, task_id: int, *, source: str, external_id: str, external_etag: str | None
    ) -> None:
        """Attach an upstream identity to a row that was created locally.

        `update`'s allowlist deliberately excludes these -- an identity is not a
        field anyone edits -- so the one legitimate case has its own method.
        """
        self.conn.execute(
            "UPDATE tasks SET external_source = ?, external_id = ?, external_etag = ?,"
            " last_synced_at = ?, dirty_at = NULL, updated_at = datetime('now')"
            " WHERE id = ?",
            (source, external_id, external_etag, _now(), task_id),
        )
        self.conn.commit()

    def in_list(self, list_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE list_id = ?", (list_id,)
        ).fetchall()


class TaskListRepository:
    """The lists tasks live in.

    Mirrors Microsoft To Do when an account is signed in -- `external_id` is the
    Graph list id -- and stands alone when none is. The two cases share one
    table because a machine that signs in later should adopt its local lists
    rather than growing a second set beside them.
    """

    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = _conn(conn)

    def create(
        self,
        name: str,
        *,
        external_source: str | None = None,
        external_id: str | None = None,
        is_default: bool = False,
        position: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO task_lists (name, external_source, external_id, is_default, position)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, external_source, external_id, 1 if is_default else 0, position),
        )
        self.conn.commit()
        return cur.lastrowid

    def get(self, list_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM task_lists WHERE id = ?", (list_id,)
        ).fetchone()

    def all(self, *, include_retired: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM task_lists"
        if not include_retired:
            sql += " WHERE retired_at IS NULL"
        sql += " ORDER BY is_default DESC, (position IS NULL), position, name COLLATE NOCASE"
        return self.conn.execute(sql).fetchall()

    def by_external(self, source: str, external_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM task_lists WHERE external_source = ? AND external_id = ?",
            (source, external_id),
        ).fetchone()

    def by_name(self, name: str) -> sqlite3.Row | None:
        """Exact, then folded, then a unique folded prefix.

        "groceries" has to find "Groceries", and "college" has to find "College
        2026" when that is the only candidate -- but never when there are two,
        because silently picking one of two lists is how a task ends up
        somewhere the user cannot find it.

        Folding also drops a decorative prefix. Real To Do lists are named
        "🛒 Groceries" and "📚 College", and nobody types the emoji: without
        this, asking for "groceries" matched nothing, made a second list called
        "groceries", and quietly split the user's shopping across two places.
        """
        wanted = _fold_list_name(name)
        if not wanted:
            return None
        rows = self.all()
        for row in rows:
            if row["name"] == (name or "").strip():
                return row
        folded = [r for r in rows if _fold_list_name(r["name"]) == wanted]
        if len(folded) == 1:
            return folded[0]
        if folded:
            return None  # genuinely ambiguous; asking beats guessing
        prefixed = [r for r in rows if _fold_list_name(r["name"]).startswith(wanted)]
        return prefixed[0] if len(prefixed) == 1 else None

    def default(self) -> sqlite3.Row | None:
        row = self.conn.execute(
            "SELECT * FROM task_lists WHERE is_default = 1 AND retired_at IS NULL"
        ).fetchone()
        if row is not None:
            return row
        rows = self.all()
        return rows[0] if rows else None

    def update(self, list_id: int, **fields: Any) -> None:
        allowed = {"name", "external_source", "external_id", "is_default", "position", "retired_at"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        clause = ", ".join(f"{k} = ?" for k in sets)
        self.conn.execute(
            f"UPDATE task_lists SET {clause}, updated_at = datetime('now') WHERE id = ?",
            (*sets.values(), list_id),
        )
        self.conn.commit()

    def clear_default(self) -> None:
        self.conn.execute("UPDATE task_lists SET is_default = 0 WHERE is_default = 1")
        self.conn.commit()

    def retire(self, list_id: int) -> None:
        """Mark a list gone upstream without losing the tasks that pointed at it.

        Same rule as a vanished task: an outage and a deleted list produce the
        same empty response, and only one of them is recoverable.
        """
        self.conn.execute(
            "UPDATE task_lists SET retired_at = ?, updated_at = datetime('now')"
            " WHERE id = ? AND retired_at IS NULL",
            (_now(), list_id),
        )
        self.conn.commit()

    def external_rows(self, source: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM task_lists WHERE external_source = ? AND retired_at IS NULL",
            (source,),
        ).fetchall()


class CalendarRepository:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = _conn(conn)

    def create(
        self,
        title: str,
        starts_at: str,
        ends_at: str,
        *,
        all_day: bool = False,
        location: str | None = None,
        busy: bool = True,
        source: str = "local",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO calendar_events (title, starts_at, ends_at, all_day, location, busy,"
            " source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, starts_at, ends_at, int(all_day), location, int(busy), source),
        )
        self.conn.commit()
        return cur.lastrowid

    def overlapping(self, starts_at: str, ends_at: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM calendar_events WHERE busy = 1 AND starts_at < ? AND ends_at > ?"
            " ORDER BY starts_at",
            (ends_at, starts_at),
        ).fetchall()

    def in_window(self, starts_at: str, ends_at: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM calendar_events WHERE starts_at < ? AND ends_at > ? ORDER BY starts_at",
            (ends_at, starts_at),
        ).fetchall()
