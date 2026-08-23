"""Repository layer. Nothing above this module issues SQL directly.

Split by domain from the start rather than accumulating into one file, which is
the one thing Khoj's otherwise-good adapters layer got wrong.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from psok.db.connection import get_connection


def _conn(conn: sqlite3.Connection | None) -> sqlite3.Connection:
    return conn or get_connection()


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
    ) -> bool:
        """Change the conversation's title or its provider/model pair.

        Provider and model are plain strings the loop re-resolves on every turn,
        so switching model mid-conversation is this write and nothing else
        (ai-runtime.md, "Switching models").
        """
        fields = {"title": title, "provider": provider, "model": model}
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
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO tasks (title, notes, due_at, scheduled_at, duration_estimate_minutes,"
            " priority, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                notes,
                due_at,
                scheduled_at,
                duration_estimate_minutes,
                priority,
                source,
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
        }
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
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
