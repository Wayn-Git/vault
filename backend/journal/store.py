"""Journal rows, and the claim that stops a day being written twice.

The claim belongs to the database, not to the runner looking first. `claim` is
an INSERT that either takes the day or does not, checked by `rowcount` against
the unique index on `(kind, entry_date)` -- the same shape as
`TaskRepository.mark_reminded`, and for the same reason: two overlapping ticks,
or a restart mid-tick, must not produce two briefings for one morning.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from backend.db.connection import get_connection

_UPDATABLE = frozenset(
    {"signals", "summary", "user_notes", "status", "model_error", "model_provider", "model_name"}
)


def _now() -> str:
    """UTC and naive, the exact shape SQLite's `datetime('now')` writes.

    `created_at` on this table is defaulted by SQLite, so `updated_at` written
    from Python has to be the same clock and the same shape or the two columns
    on one row disagree about which is later.
    """
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


class JournalStore:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_connection()

    def claim(self, kind: str, entry_date: str, signals: dict) -> int | None:
        """Take this day for this kind, or return None because it is taken."""
        cursor = self.conn.execute(
            "INSERT INTO journal_entries (kind, entry_date, signals, status, updated_at)"
            " VALUES (?, ?, ?, 'open', ?)"
            " ON CONFLICT (kind, entry_date) DO NOTHING",
            (kind, entry_date, json.dumps(signals), _now()),
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            return None
        return int(cursor.lastrowid)

    def get(self, entry_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM journal_entries WHERE id = ?", (entry_id,)
        ).fetchone()

    def by_date(self, kind: str, entry_date: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM journal_entries WHERE kind = ? AND entry_date = ?", (kind, entry_date)
        ).fetchone()

    def latest(self, kind: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM journal_entries WHERE kind = ? ORDER BY entry_date DESC, id DESC"
            " LIMIT 1",
            (kind,),
        ).fetchone()

    def recent(self, *, kind: str | None = None, limit: int = 30) -> list[sqlite3.Row]:
        sql = "SELECT * FROM journal_entries"
        params: list = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY entry_date DESC, id DESC LIMIT ?"
        params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    def between(self, start: str, end: str, *, kind: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM journal_entries WHERE entry_date >= ? AND entry_date <= ?"
        params: list = [start, end]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY entry_date, id"
        return self.conn.execute(sql, params).fetchall()

    def update(self, entry_id: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in _UPDATABLE}
        if not allowed:
            return
        if isinstance(allowed.get("signals"), dict):
            allowed["signals"] = json.dumps(allowed["signals"])
        clauses = ", ".join(f"{key} = ?" for key in allowed)
        self.conn.execute(
            f"UPDATE journal_entries SET {clauses}, updated_at = ? WHERE id = ?",
            (*allowed.values(), _now(), entry_id),
        )
        self.conn.commit()

    def delete(self, entry_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
        self.conn.commit()
        return cursor.rowcount > 0
