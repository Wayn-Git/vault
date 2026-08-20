"""Persistence for long-term memory.

Deliberately reuses the retrieval layer's `sqlite-vec` machinery rather than
standing up a second vector story: same extension loader, same serialization,
same graceful degradation when the extension is missing. The only thing that is
separate is the table, because memory vectors and chunk vectors are different
populations searched at different times.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from psok.db.connection import get_connection
from psok.retrieval.store import load_extension, serialize

log = logging.getLogger(__name__)

# Which model embedded the memories, recorded for the same reason the document
# index records its own: a query embedded by a different model lands in an
# unrelated vector space and returns plausible nonsense instead of failing.
MODEL_SETTING = "memory_embedding_model"
DIMENSIONS_SETTING = "memory_embedding_dimensions"


@dataclass
class Memory:
    id: int
    fact: str
    conversation_id: str | None
    created_at: str


def _row(row: sqlite3.Row) -> Memory:
    return Memory(
        id=row["id"],
        fact=row["fact"],
        conversation_id=row["conversation_id"],
        created_at=row["created_at"],
    )


class MemoryStore:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_connection()

    # ------------------------------------------------------------- facts

    def add(self, fact: str, conversation_id: str | None = None) -> int:
        cursor = self.conn.execute(
            "INSERT INTO memories (fact, conversation_id) VALUES (?, ?)",
            (fact, conversation_id),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def supersede(self, memory_ids: list[int]) -> int:
        """Retire facts without deleting them. Returns how many were still live."""
        if not memory_ids:
            return 0
        placeholders = ",".join("?" * len(memory_ids))
        cursor = self.conn.execute(
            f"UPDATE memories SET superseded_at = datetime('now')"
            f" WHERE id IN ({placeholders}) AND superseded_at IS NULL",
            memory_ids,
        )
        self.conn.commit()
        self._drop_vectors(memory_ids)
        return cursor.rowcount

    def live(self, limit: int = 200) -> list[Memory]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_at IS NULL"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row(r) for r in rows]

    def recent(self, days: int, limit: int) -> list[Memory]:
        """The recency half of recall."""
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE superseded_at IS NULL"
            " AND created_at >= datetime('now', ?)"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (f"-{int(days)} days", limit),
        ).fetchall()
        return [_row(r) for r in rows]

    def get_many(self, memory_ids: list[int]) -> list[Memory]:
        if not memory_ids:
            return []
        placeholders = ",".join("?" * len(memory_ids))
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE id IN ({placeholders}) AND superseded_at IS NULL",
            memory_ids,
        ).fetchall()
        return [_row(r) for r in rows]

    # ----------------------------------------------------------- vectors

    def ensure_index(self, dimensions: int) -> bool:
        """Create the vec0 table, rebuilding it if the dimension count changed."""
        if not load_extension(self.conn):
            return False

        existing = self.conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (DIMENSIONS_SETTING,)
        ).fetchone()
        if existing and int(existing["value"]) != dimensions:
            log.warning(
                "memory embedding dimensions changed from %s to %s; dropping the vector index",
                existing["value"],
                dimensions,
            )
            self.conn.execute("DROP TABLE IF EXISTS memory_vectors")

        try:
            self.conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors USING vec0("
                f" memory_id INTEGER PRIMARY KEY, embedding float[{dimensions}])"
            )
        except sqlite3.OperationalError as exc:
            # Recency recall still works without this, so a vector failure
            # degrades memory rather than disabling it.
            log.warning("could not create the memory vector index: %s", exc)
            return False

        self.conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = datetime('now')",
            (DIMENSIONS_SETTING, str(dimensions)),
        )
        self.conn.commit()
        return True

    def index(self, memory_id: int, embedding: list[float]) -> None:
        if not embedding or not self.ensure_index(len(embedding)):
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO memory_vectors (memory_id, embedding) VALUES (?, ?)",
            (memory_id, serialize(embedding)),
        )
        self.conn.commit()

    def _drop_vectors(self, memory_ids: list[int]) -> None:
        if not memory_ids or not load_extension(self.conn):
            return
        placeholders = ",".join("?" * len(memory_ids))
        try:
            self.conn.execute(
                f"DELETE FROM memory_vectors WHERE memory_id IN ({placeholders})", memory_ids
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # no vector index yet; nothing to remove

    def search(self, embedding: list[float], limit: int) -> list[int]:
        """The semantic half of recall. Empty when vectors are unavailable."""
        if not load_extension(self.conn):
            return []
        try:
            rows = self.conn.execute(
                "SELECT memory_id FROM memory_vectors"
                " WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (serialize(embedding), limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("memory vector search failed: %s", exc)
            return []
        return [r["memory_id"] for r in rows]

    # ---------------------------------------------------- embedder pinning

    def record_embedding_model(self, provider: str, model: str) -> None:
        self.conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = datetime('now')",
            (MODEL_SETTING, f"{provider}:{model}"),
        )
        self.conn.commit()

    def embedding_model(self) -> tuple[str, str] | None:
        row = self.conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (MODEL_SETTING,)
        ).fetchone()
        if not row or ":" not in row["value"]:
            return None
        provider, _, model = row["value"].partition(":")
        return provider, model

    # ------------------------------------------------------------- toggle

    def is_enabled(self, conversation_id: str | None = None) -> bool:
        """Most specific wins, mirroring capability resolution. Default on."""
        if conversation_id:
            row = self.conn.execute(
                "SELECT enabled FROM memory_state WHERE scope = ?", (conversation_id,)
            ).fetchone()
            if row is not None:
                return bool(row["enabled"])
        row = self.conn.execute(
            "SELECT enabled FROM memory_state WHERE scope = 'global'"
        ).fetchone()
        return True if row is None else bool(row["enabled"])

    def set_enabled(self, enabled: bool, *, conversation_id: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO memory_state (scope, enabled) VALUES (?, ?)"
            " ON CONFLICT(scope) DO UPDATE SET"
            " enabled = excluded.enabled, updated_at = datetime('now')",
            (conversation_id or "global", int(enabled)),
        )
        self.conn.commit()

    def clear_setting(self, *, conversation_id: str | None = None) -> None:
        self.conn.execute(
            "DELETE FROM memory_state WHERE scope = ?", (conversation_id or "global",)
        )
        self.conn.commit()
