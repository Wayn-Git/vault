"""Rows for the library, and where its text lives on disk.

The repository idiom of `backend/db/repositories.py`: a connection injected or
taken from the process singleton, raw `sqlite3.Row` out, commits its own writes,
local-naive timestamps written by Python rather than by SQLite's UTC `now`.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from backend.config import paths
from backend.db.connection import get_connection

#: What a library item can be. Not a CHECK constraint -- SQLite cannot alter one
#: in place, and this list will grow. The service validates against it and names
#: the accepted values in the error.
KINDS = ("article", "book", "video", "podcast", "newsletter", "paper", "note", "other")

#: Longest slug in a filename, leaving room for the id prefix and the extension
#: inside the 255-byte limit every filesystem in play here shares.
MAX_SLUG_CHARS = 80

_UPDATABLE = frozenset(
    {
        "kind",
        "title",
        "url",
        "author",
        "site",
        "published_on",
        "consumed_on",
        "notes",
        "rating",
        "document_id",
        "text_path",
        "capture_note",
        "word_count",
    }
)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def library_dir() -> Path:
    directory = paths().library_dir
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def slugify(title: str) -> str:
    slug = _SLUG_STRIP.sub("-", (title or "").lower()).strip("-")
    return slug[:MAX_SLUG_CHARS].strip("-") or "untitled"


def text_path(item_id: int, title: str) -> Path:
    """Where one item's text is kept.

    The id leads, so two articles with the same title cannot collide -- which is
    also what makes `documents.path` UNIQUE impossible to trip.
    """
    return library_dir() / f"{item_id:06d}-{slugify(title)}.md"


class LibraryStore:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_connection()

    def create(
        self,
        *,
        kind: str,
        title: str,
        url: str | None = None,
        author: str | None = None,
        site: str | None = None,
        published_on: str | None = None,
        consumed_on: str | None = None,
        notes: str | None = None,
        rating: int | None = None,
    ) -> int:
        cursor = self.conn.execute(
            "INSERT INTO library_items (kind, title, url, author, site, published_on,"
            " consumed_on, notes, rating, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                title,
                url,
                author,
                site,
                published_on,
                consumed_on or _today(),
                notes,
                rating,
                _now(),
                _now(),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update(self, item_id: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in _UPDATABLE}
        if not allowed:
            return
        clauses = ", ".join(f"{key} = ?" for key in allowed)
        self.conn.execute(
            f"UPDATE library_items SET {clauses}, updated_at = ? WHERE id = ?",
            (*allowed.values(), _now(), item_id),
        )
        self.conn.commit()

    def get(self, item_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM library_items WHERE id = ?", (item_id,)
        ).fetchone()

    def by_url(self, url: str) -> sqlite3.Row | None:
        """The most recent item logged for this URL, if any."""
        return self.conn.execute(
            "SELECT * FROM library_items WHERE url = ? ORDER BY id DESC LIMIT 1", (url,)
        ).fetchone()

    def by_document(self, document_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM library_items WHERE document_id = ?", (document_id,)
        ).fetchone()

    def by_document_ids(self, document_ids: list[int]) -> dict[int, sqlite3.Row]:
        if not document_ids:
            return {}
        placeholders = ",".join("?" * len(document_ids))
        rows = self.conn.execute(
            f"SELECT * FROM library_items WHERE document_id IN ({placeholders})", document_ids
        ).fetchall()
        return {row["document_id"]: row for row in rows}

    def list(
        self,
        *,
        kind: str | None = None,
        since: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM library_items"
        params: list = []
        where = []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if since:
            where.append("consumed_on >= ?")
            params.append(since)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY consumed_on DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return self.conn.execute(sql, params).fetchall()

    def consumed_on(self, day: str) -> list[sqlite3.Row]:
        """Everything logged for one local calendar day. The journal's signal."""
        return self.conn.execute(
            "SELECT * FROM library_items WHERE consumed_on = ? ORDER BY id", (day,)
        ).fetchall()

    def consumed_between(self, start: str, end: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM library_items WHERE consumed_on >= ? AND consumed_on <= ?"
            " ORDER BY consumed_on, id",
            (start, end),
        ).fetchall()

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT kind, COUNT(*) AS n FROM library_items GROUP BY kind"
        ).fetchall()
        return {row["kind"]: row["n"] for row in rows}

    def delete(self, item_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM library_items WHERE id = ?", (item_id,))
        self.conn.commit()
        return cursor.rowcount > 0
