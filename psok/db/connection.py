"""SQLite connection management and schema bootstrap.

WAL mode plus a busy timeout is what lets background sync workers write while a
conversation turn reads (see docs/architecture/data-model.md).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from psok.config import paths

log = logging.getLogger(__name__)

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
    _add_missing_columns(conn)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring an older database up to the current shape before applying the schema.

    Every statement in schema.sql is `IF NOT EXISTS`, which is a no-op against a
    table that already exists in an *older* shape -- and then an index over a
    column that table does not have fails, taking startup down with a bare
    "no such column". A database from a previous version of PSOK is the normal
    case for a single user upgrading in place, so it has to be handled here
    rather than by asking them to delete their data.

    Columns are compared against a throwaway database built from the schema
    itself, so this stays true as the schema changes without a second list of
    columns to keep in step.
    """
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if not existing:
        return  # a fresh database; schema.sql creates everything

    reference = sqlite3.connect(":memory:")
    try:
        reference.executescript(SCHEMA_PATH.read_text())
        for table in existing:
            wanted = list(reference.execute(f"PRAGMA table_info({table})"))
            if not wanted:
                continue  # a table this version no longer defines; left alone
            have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for _, name, column_type, not_null, default, _pk in wanted:
                if name in have:
                    continue
                clause = f"ALTER TABLE {table} ADD COLUMN {name} {column_type}"
                if default is not None:
                    clause += f" DEFAULT {default}"
                elif not_null:
                    # SQLite cannot add a NOT NULL column without a default, and
                    # guessing a value for the user's rows is worse than saying so.
                    log.error(
                        "cannot add required column %s.%s to an existing database;"
                        " it needs migrating by hand",
                        table,
                        name,
                    )
                    continue
                try:
                    conn.execute(clause)
                    log.info("added missing column %s.%s", table, name)
                except sqlite3.OperationalError as exc:
                    log.error("could not add column %s.%s: %s", table, name, exc)
        conn.commit()
    finally:
        reference.close()


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
