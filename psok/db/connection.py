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
    _adopt_existing_automation_runs(conn)
    _drop_empty_legacy_tables(conn)
    _drop_retired_columns(conn)
    _normalise_task_timestamps(conn)
    _repair_placeholder_models(conn)


# Tables an older PSOK created and this one has no code for. Dropping is guarded
# on emptiness: a table nothing references but that somehow holds rows is a
# surprise worth keeping, not tidying away.
LEGACY_TABLES = ("integrations", "integration_state")


# Columns an older PSOK wrote that this one has no code for, with the indexes
# that have to go first -- SQLite refuses to drop a column an index still names.
#
# `tasks.my_day_on` held the date a task was put in My Day, back when My Day was
# a stamp three separate gestures could write. It is a list now, so the column
# has no writer, and a column with no writer that a query could still reach is
# the "reserved slot" this codebase does not keep. The dates are not migrated
# into the list: they were mostly written by a sun press days ago, and silently
# moving old tasks into the user's live My Day list -- which would then push
# them to their phone -- is a worse first impression than an empty list they
# fill themselves.
RETIRED_COLUMNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("tasks", "my_day_on", ("idx_tasks_my_day",)),
)


def _drop_retired_columns(conn: sqlite3.Connection) -> None:
    for table, column, indexes in RETIRED_COLUMNS:
        try:
            have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.OperationalError:
            continue
        if column not in have:
            continue
        for index in indexes:
            conn.execute(f"DROP INDEX IF EXISTS {index}")
        try:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            log.info("dropped retired column %s.%s", table, column)
        except sqlite3.OperationalError as exc:
            # Old SQLite (DROP COLUMN landed in 3.35) or a view still naming it.
            # Left in place rather than failing the migration: an unused column
            # is harmless, and taking the database down on start is not.
            log.error("could not drop retired column %s.%s: %s", table, column, exc)
    conn.commit()


# What an interface once sent when it did not yet know a provider's default.
PLACEHOLDER_MODELS = ("default", "", "null", "undefined", "none")


def _repair_placeholder_models(conn: sqlite3.Connection) -> None:
    """Point conversations stored with a placeholder model at a real one.

    The composer used to send the literal string `default` when `/api/health`
    had not answered yet. It reached the provider verbatim -- NVIDIA replies
    `404 page not found` -- so every turn in that conversation failed forever,
    and nothing in the interface offered a way to correct it.

    The send is refused at the API now; this repairs the rows that predate that.
    """
    try:
        rows = conn.execute(
            "SELECT id, provider FROM conversations WHERE model IS NULL OR lower(model) IN"
            f" ({','.join('?' * len(PLACEHOLDER_MODELS))})",
            PLACEHOLDER_MODELS,
        ).fetchall()
    except sqlite3.OperationalError:
        return
    if not rows:
        return

    try:
        from psok.config import load_providers

        defaults = {
            name: config.default_model
            for name, config in load_providers().items()
            if config.default_model
        }
    except Exception as exc:
        log.debug("could not read provider defaults to repair conversations: %s", exc)
        return

    repaired = 0
    for conversation_id, provider in rows:
        model = defaults.get(provider)
        if not model:
            continue
        conn.execute(
            "UPDATE conversations SET model = ?, updated_at = datetime('now') WHERE id = ?",
            (model, conversation_id),
        )
        repaired += 1
    if repaired:
        log.info("repaired %d conversations stored with a placeholder model", repaired)
    conn.commit()


# Columns holding a local naive timestamp that SQLite compares as a string.
_TASK_TIME_COLUMNS = ("due_at", "scheduled_at", "reminder_at", "reminded_at")


def _normalise_task_timestamps(conn: sqlite3.Connection) -> None:
    """Rewrite `YYYY-MM-DDTHH:MM:SS` to `YYYY-MM-DD HH:MM:SS`.

    Two writers disagreed about the separator -- the To Do sync used a space and
    the hand-written API path used `datetime.isoformat()`, which uses `T` -- and
    SQLite compares both as plain strings. Sorting survives that, which is why
    it went unnoticed, but the reminder scan does not: `T` is 0x54 and a space is
    0x20, so `'2026-08-27T09:00:00' <= '2026-08-27 11:30:00'` is **false**, and a
    reminder written in the `T` form is skipped every tick until the date rolls
    over and the day digits decide the comparison instead.

    One writer now produces both forms' replacement, so this only ever has rows
    to fix once.
    """
    try:
        # Safe to apply to every column of a matched row: the separator is at
        # position 11 either way, so rewriting one that already holds a space
        # reproduces it exactly.
        clauses = ", ".join(
            f"{c} = substr({c}, 1, 10) || ' ' || substr({c}, 12)" for c in _TASK_TIME_COLUMNS
        )
        where = " OR ".join(f"{c} LIKE '____-__-__T%'" for c in _TASK_TIME_COLUMNS)
        cur = conn.execute(f"UPDATE tasks SET {clauses} WHERE {where}")
    except sqlite3.OperationalError:
        return  # no tasks table yet
    if cur.rowcount:
        log.info("normalised the timestamp separator on %d task rows", cur.rowcount)
    conn.commit()


def _drop_empty_legacy_tables(conn: sqlite3.Connection) -> None:
    """Remove tables this version defines no code for, only while they are empty.

    `schema.sql` is entirely `IF NOT EXISTS`, so a table removed from it simply
    stays in every database that already had one -- which is how a reserved slot
    outlives the decision to drop it. These two were left by a version that had
    an integrations concept; `psok/` has no reference to either.
    """
    for table in LEGACY_TABLES:
        try:
            rows = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            continue  # already gone, or never created
        if rows:
            log.warning("legacy table %s holds %d rows; leaving it alone", table, rows)
            continue
        try:
            conn.execute(f"DROP TABLE {table}")
            log.info("dropped empty legacy table %s", table)
        except sqlite3.OperationalError as exc:
            log.error("could not drop legacy table %s: %s", table, exc)
    conn.commit()


def _adopt_existing_automation_runs(conn: sqlite3.Connection) -> None:
    """Claim runs written before `conversations.automation_id` existed.

    Adding the column leaves every run made before it NULL, which reads as "a
    person started this" -- so those keep crowding the rail and are never
    pruned. On the machine this was written for that is 31 of 111
    conversations. They are recognised the only way available after the fact:
    the title `run` gave them, `f"{name} · automation"`, matched against an
    automation that still carries that name. A conversation someone happened to
    title that way is claimed too, which is why the match must be exact rather
    than a suffix search, and why this only ever runs against NULL rows.
    """
    try:
        rows = conn.execute(
            "SELECT id, name FROM automations WHERE name IS NOT NULL AND name != ''"
        ).fetchall()
    except sqlite3.OperationalError:
        return  # no automations table yet; nothing to adopt

    for automation_id, name in rows:
        conn.execute(
            "UPDATE conversations SET automation_id = ?"
            " WHERE automation_id IS NULL AND title = ?",
            (str(automation_id), f"{name} · automation"),
        )
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
