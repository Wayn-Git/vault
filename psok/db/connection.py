"""SQLite connection management and schema bootstrap.

WAL mode plus a busy timeout is what lets background sync workers write while a
conversation turn reads (see docs/architecture/data-model.md).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from psok.config import paths

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_connection: sqlite3.Connection | None = None


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or paths().db
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    _configure(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def get_connection() -> sqlite3.Connection:
    """Process-wide connection, created and migrated on first use."""
    global _connection
    if _connection is None:
        _connection = connect()
        migrate(_connection)
    return _connection


def reset_connection() -> None:
    """Drop the cached connection. Used by tests and by PSOK_HOME changes."""
    global _connection
    if _connection is not None:
        _connection.close()
    _connection = None


@contextmanager
def transaction(conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
    """Short transaction. Sync workers use one of these per item, never one per sync."""
    c = conn or get_connection()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
