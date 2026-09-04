"""The inbound queue.

Two properties do all the work here, and both belong to the database rather than
to code that looks before it writes:

**One delivery is acted on once.** `delivery_key` is UNIQUE and `enqueue` is an
`INSERT OR IGNORE`. Meta re-delivers anything it did not see a 200 for, and a
retry must be indistinguishable from a replay: nothing inserted, and the caller
still answers 200 so the retries stop.

**One event is claimed by one drain.** `claim_next` is a single conditional
`UPDATE` -- the same idiom as `JournalStore.claim` and `TaskRepository.mark_reminded`
-- so two overlapping drains cannot both take the same row and save the same reel
twice.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from backend.db.connection import get_connection
from backend.instagram.webhook import Inbound

TERMINAL = ("done", "failed", "ignored")

#: Above this the queue is not a queue, it is somebody filling the table. The
#: webhook still answers 200 -- refusing would only make Meta retry -- but
#: nothing more is written and the interface says so.
MAX_QUEUED = 500

#: How long a row may sit in `working` before a drain is presumed dead. Above the
#: worst honest case: a long download, ffmpeg, and a slow transcription.
STALE_SECONDS = 600

#: Attempts before a row is given up on, so a permanently broken delivery is not
#: retried forever.
MAX_ATTEMPTS = 3


def _now() -> str:
    """Local naive, matching every other timestamp Python writes in this repo."""
    return datetime.now().isoformat(sep=" ", timespec="seconds")


class InstagramEventStore:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_connection()

    def enqueue(self, inbound: Inbound) -> int | None:
        """Write one delivery down. None means it was already here."""
        cursor = self.conn.execute(
            "INSERT INTO instagram_events (delivery_key, route, sender_id, payload,"
            " status, received_at) VALUES (?, ?, ?, ?, 'queued', ?)"
            " ON CONFLICT (delivery_key) DO NOTHING",
            (
                inbound.delivery_key,
                inbound.route,
                inbound.sender_id,
                json.dumps(inbound.raw),
                _now(),
            ),
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            return None
        return int(cursor.lastrowid)

    def claim_next(self) -> sqlite3.Row | None:
        """Take the oldest queued event, or None. The claim is the database's."""
        cursor = self.conn.execute(
            "UPDATE instagram_events SET status = 'working', attempts = attempts + 1,"
            " started_at = ? WHERE id = ("
            "  SELECT id FROM instagram_events WHERE status = 'queued' ORDER BY id LIMIT 1)",
            (_now(),),
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.conn.execute(
            "SELECT * FROM instagram_events WHERE status = 'working' ORDER BY started_at DESC,"
            " id DESC LIMIT 1"
        ).fetchone()

    def reclaim_stale(self, *, older_than_seconds: int = STALE_SECONDS) -> int:
        """Put back anything a dead drain was holding.

        A crash mid-download leaves a row in `working` that nothing will ever
        finish. Rows past `MAX_ATTEMPTS` are failed rather than requeued, so a
        delivery that crashes the drain every time does not do so forever.
        """
        cutoff = (datetime.now() - timedelta(seconds=older_than_seconds)).isoformat(
            sep=" ", timespec="seconds"
        )
        self.conn.execute(
            "UPDATE instagram_events SET status = 'failed', finished_at = ?,"
            " note = 'this delivery was interrupted too many times to keep retrying'"
            " WHERE status = 'working' AND started_at < ? AND attempts >= ?",
            (_now(), cutoff, MAX_ATTEMPTS),
        )
        cursor = self.conn.execute(
            "UPDATE instagram_events SET status = 'queued' WHERE status = 'working'"
            " AND started_at < ?",
            (cutoff,),
        )
        self.conn.commit()
        return cursor.rowcount

    def finish(
        self,
        event_id: int,
        *,
        status: str,
        note: str | None = None,
        library_item_id: int | None = None,
    ) -> None:
        if status not in TERMINAL and status != "queued":
            raise ValueError(f"unknown status '{status}'")
        self.conn.execute(
            "UPDATE instagram_events SET status = ?, note = ?, library_item_id = ?,"
            " finished_at = ? WHERE id = ?",
            (status, note, library_item_id, _now() if status in TERMINAL else None, event_id),
        )
        self.conn.commit()

    def requeue(self, event_id: int) -> bool:
        """Send one event round again, attempts reset. The Retry button."""
        cursor = self.conn.execute(
            "UPDATE instagram_events SET status = 'queued', attempts = 0, note = NULL,"
            " started_at = NULL, finished_at = NULL WHERE id = ?",
            (event_id,),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get(self, event_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM instagram_events WHERE id = ?", (event_id,)
        ).fetchone()

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM instagram_events GROUP BY status"
        ).fetchall()
        return {row["status"]: row["n"] for row in rows}

    def queued_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM instagram_events WHERE status IN ('queued', 'working')"
        ).fetchone()[0]

    def recent(self, *, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM instagram_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def unknown_senders(self, *, limit: int = 20) -> list[sqlite3.Row]:
        """Who has sent something that was turned away, most recent first.

        An IGSID is an opaque seventeen-digit number nobody can look up, so the
        only workable way to fill the allowlist is from a message that actually
        arrived. This is what the interface offers as "@someone sent you a reel
        -- allow them?".
        """
        return self.conn.execute(
            "SELECT sender_id, COUNT(*) AS attempts, MAX(received_at) AS last_seen"
            " FROM instagram_events WHERE status = 'ignored' AND sender_id IS NOT NULL"
            " GROUP BY sender_id ORDER BY last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def accepted_since(self, sender_id: str, *, seconds: int = 3600) -> int:
        """How many of this sender's events were taken recently. The per-sender cap."""
        cutoff = (datetime.now() - timedelta(seconds=seconds)).isoformat(
            sep=" ", timespec="seconds"
        )
        return self.conn.execute(
            "SELECT COUNT(*) FROM instagram_events WHERE sender_id = ? AND received_at >= ?"
            " AND status != 'ignored'",
            (sender_id, cutoff),
        ).fetchone()[0]

    def prune(self, *, keep_days: int = 30) -> int:
        """Drop settled events. The library item is the record; this is the receipt."""
        cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat(
            sep=" ", timespec="seconds"
        )
        cursor = self.conn.execute(
            "DELETE FROM instagram_events WHERE status IN ('done', 'ignored')"
            " AND received_at < ?",
            (cutoff,),
        )
        self.conn.commit()
        return cursor.rowcount
