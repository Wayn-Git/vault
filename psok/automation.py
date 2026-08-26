"""Automations: a turn that runs without anyone typing. **Beta.**

The smallest thing that is honestly a scheduled turn, and no more. A prompt, an
interval, and a record of what happened -- with two decisions made explicitly
rather than left to be discovered later:

**Who decides it is time.** This process, while `psok serve` is running. A
cron-like daemon would keep automations running when the API is down, which
sounds better until you ask what it does with a turn that needs a permission
answer at 3am. Tying them to the server means "automations run while PSOK is
open", which is a rule that can be stated in one sentence and is true.

**What the permission gate does when nobody is watching.** It denies. An
unattended turn cannot raise a prompt -- there is no one to answer it, and a
prompt that blocks forever is worse than a refusal -- so the gate runs with a
callback that says no to everything not already covered by a standing approval
the user granted deliberately. An automation that needs more than that records
`blocked` and says which operation it wanted, so the fix is to approve that one
operation rather than to loosen anything globally.

Both are beta positions, not final ones. See docs/architecture/automation.md.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from psok.db.connection import get_connection

log = logging.getLogger(__name__)

# Below this an "automation" is a busy loop wearing a schedule.
MIN_MINUTES = 5
MAX_MINUTES = 60 * 24 * 30

# How often the runner wakes to look for due work. The check is one indexed
# read, so this is cheap; it also bounds how late a run can be.
TICK_SECONDS = 30

# An automation that hangs must not wedge the runner for the rest of the session.
RUN_TIMEOUT_SECONDS = 300

# How many past runs of one automation to keep. Enough to compare a failure
# against the run before it, which is the usual reason to look at all, without
# keeping every run an enabled automation has ever made.
KEEP_RUNS = 20


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass
class Automation:
    id: int
    name: str
    prompt: str
    every_minutes: int
    enabled: bool
    provider: str | None
    model: str | None
    next_run_at: str
    last_run_at: str | None
    last_status: str | None
    last_summary: str | None
    last_conversation_id: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Automation:
        return cls(
            id=row["id"],
            name=row["name"],
            prompt=row["prompt"],
            every_minutes=row["every_minutes"],
            enabled=bool(row["enabled"]),
            provider=row["provider"],
            model=row["model"],
            next_run_at=row["next_run_at"],
            last_run_at=row["last_run_at"],
            last_status=row["last_status"],
            last_summary=row["last_summary"],
            last_conversation_id=row["last_conversation_id"],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "every_minutes": self.every_minutes,
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "last_summary": self.last_summary,
            "last_conversation_id": self.last_conversation_id,
        }


class AutomationError(ValueError):
    pass


class AutomationRepository:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_connection()

    def create(
        self,
        name: str,
        prompt: str,
        every_minutes: int,
        *,
        provider: str | None = None,
        model: str | None = None,
        enabled: bool = True,
        first_run: datetime | None = None,
    ) -> Automation:
        clean_name = " ".join(name.split())
        clean_prompt = prompt.strip()
        if not clean_name:
            raise AutomationError("an automation needs a name")
        if not clean_prompt:
            raise AutomationError("an automation with no prompt has nothing to run")
        if not MIN_MINUTES <= every_minutes <= MAX_MINUTES:
            raise AutomationError(
                f"the interval must be between {MIN_MINUTES} minutes and 30 days"
            )
        # Scheduled forward by default: creating one must not fire it that
        # second, which is how a mistyped prompt runs before it is re-read.
        due = first_run or (_now() + timedelta(minutes=every_minutes))
        cursor = self.conn.execute(
            "INSERT INTO automations (name, prompt, every_minutes, enabled, provider, model,"
            " next_run_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (clean_name, clean_prompt, every_minutes, int(enabled), provider, model, _iso(due)),
        )
        self.conn.commit()
        return self.get(cursor.lastrowid)  # type: ignore[return-value]

    def get(self, automation_id: int) -> Automation | None:
        row = self.conn.execute(
            "SELECT * FROM automations WHERE id = ?", (automation_id,)
        ).fetchone()
        return Automation.from_row(row) if row else None

    def list(self) -> list[Automation]:
        return [
            Automation.from_row(r)
            for r in self.conn.execute("SELECT * FROM automations ORDER BY next_run_at")
        ]

    def due(self, moment: datetime | None = None) -> list[Automation]:
        return [
            Automation.from_row(r)
            for r in self.conn.execute(
                "SELECT * FROM automations WHERE enabled = 1 AND next_run_at <= ?"
                " ORDER BY next_run_at",
                (_iso(moment or _now()),),
            )
        ]

    def update(self, automation_id: int, **fields: Any) -> Automation | None:
        allowed = {"name", "prompt", "every_minutes", "enabled", "provider", "model"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "every_minutes" in updates and not (
            MIN_MINUTES <= updates["every_minutes"] <= MAX_MINUTES
        ):
            raise AutomationError(
                f"the interval must be between {MIN_MINUTES} minutes and 30 days"
            )
        if "enabled" in updates:
            updates["enabled"] = int(updates["enabled"])
        if not updates:
            return self.get(automation_id)
        assignments = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE automations SET {assignments} WHERE id = ?",
            (*updates.values(), automation_id),
        )
        # A changed interval moves the next run, or an automation switched from
        # daily to hourly waits out the rest of the day it was already given.
        if "every_minutes" in updates:
            self.conn.execute(
                "UPDATE automations SET next_run_at = ? WHERE id = ?",
                (_iso(_now() + timedelta(minutes=updates["every_minutes"])), automation_id),
            )
        self.conn.commit()
        return self.get(automation_id)

    def delete(self, automation_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_running(self, automation_id: int) -> None:
        self.conn.execute(
            "UPDATE automations SET last_status = 'running', last_run_at = ? WHERE id = ?",
            (_iso(_now()), automation_id),
        )
        self.conn.commit()

    def record(
        self,
        automation_id: int,
        *,
        status: str,
        summary: str,
        conversation_id: str | None,
        every_minutes: int,
    ) -> None:
        """Write the outcome and schedule the next run.

        Rescheduled from now rather than from the last due time on purpose: a
        server that was off for a day should not come back and fire twenty-four
        catch-up runs of an hourly automation.
        """
        self.conn.execute(
            "UPDATE automations SET last_status = ?, last_summary = ?,"
            " last_conversation_id = ?, last_run_at = ?, next_run_at = ? WHERE id = ?",
            (
                status,
                summary[:400],
                conversation_id,
                _iso(_now()),
                _iso(_now() + timedelta(minutes=every_minutes)),
                automation_id,
            ),
        )
        self.conn.commit()
        # Runs accumulated for as long as the automation was enabled, because
        # nothing ever removed one.
        from psok.db.repositories import ConversationRepository

        ConversationRepository(self.conn).prune_runs(str(automation_id), KEEP_RUNS)


class UnattendedGate:
    """The permission gate, with nobody at the keyboard.

    Standing approvals are checked before this is ever reached, so an automation
    can do anything the user has deliberately said may run without asking, and
    nothing else.

    It **denies** rather than raising. Raising looked right -- it carried the
    operation key straight out -- but the loop turns any exception into a failed
    turn, so a scheduled run that wanted one thing it could not have reported
    nothing but a stack-trace-shaped string and did none of the rest of its work.
    A denial is a thing the loop already knows how to handle: the model is told
    the call was refused and carries on, and what was refused is collected here
    so the automation can name it afterwards.
    """

    def __init__(self) -> None:
        self.refused: list[str] = []

    async def __call__(self, request) -> bool:
        if request.operation_key not in self.refused:
            self.refused.append(request.operation_key)
        return False


async def run_once(
    automation: Automation,
    *,
    director_for,
    repo: AutomationRepository | None = None,
) -> dict[str, Any]:
    """Run one automation and record what happened.

    `director_for` is passed in rather than imported so this stays testable
    without a server: it takes the deny-everything confirmation callback and
    returns something with `.run(conversation_id, prompt)`.
    """
    from psok.config import configured_providers
    from psok.db.repositories import ConversationRepository

    repo = repo or AutomationRepository()
    repo.mark_running(automation.id)

    # Only providers with a key. An automation runs with nobody watching, so
    # picking one that cannot answer costs a failed run every interval until
    # someone reads the record.
    providers = configured_providers()
    provider = automation.provider
    model = automation.model
    if not provider:
        if not providers:
            repo.record(
                automation.id,
                status="error",
                summary="no provider is configured in providers.yaml",
                conversation_id=None,
                every_minutes=automation.every_minutes,
            )
            return {"status": "error", "summary": "no provider is configured"}
        provider = "nvidia" if "nvidia" in providers else sorted(providers)[0]

    # Outside the branch above on purpose: an automation created with a provider
    # but no model wrote the literal string "default" onto its conversation, and
    # the provider's own declared model is right there in providers.yaml.
    if not model and (chosen := providers.get(provider)) is not None:
        model = chosen.default_model

    conversation_id = ConversationRepository().create(
        provider,
        model or "default",
        f"{automation.name} · automation",
        automation_id=automation.id,
    )

    answer = ""
    status = "ok"
    summary = ""
    gate = UnattendedGate()
    try:
        director = director_for(gate)
        async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
            async for event in director.run(conversation_id, automation.prompt):
                if event.type in ("assistant_delta", "assistant_text"):
                    answer += event.data.get("text", "")
                elif event.type == "error":
                    status, summary = "error", event.data.get("message", "failed")
                elif event.type == "guard":
                    status, summary = "error", event.data.get("reason", "stopped")
                elif event.type == "done":
                    answer = event.data.get("text", answer)
    except TimeoutError:
        status = "error"
        summary = f"took longer than {RUN_TIMEOUT_SECONDS // 60} minutes and was stopped"
    except Exception as exc:  # a broken automation must not stop the runner
        status = "error"
        summary = f"{type(exc).__name__}: {exc}"
        log.exception("automation %s failed", automation.id)

    # Anything refused outranks a clean finish: the turn completed, but not the
    # part that needed permission, and saying "ok" would be a lie by omission.
    # Naming the exact operations is the whole value -- the fix is to approve
    # those, once, rather than to give scheduled work a blanket exemption.
    if gate.refused and status != "error":
        status = "blocked"
        summary = (
            f"needs permission for {', '.join(gate.refused)}. Approve each once from a"
            " conversation with \u201cdon\u2019t ask again\u201d and this will run unattended."
        )
    elif status == "ok" and not summary:
        summary = " ".join(answer.split())[:400] or "ran, and said nothing"

    repo.record(
        automation.id,
        status=status,
        summary=summary,
        conversation_id=conversation_id,
        every_minutes=automation.every_minutes,
    )
    return {"status": status, "summary": summary, "conversation_id": conversation_id}


class AutomationRunner:
    """Wakes every half minute, runs whatever is due, one at a time.

    One at a time on purpose: three automations that come due in the same minute
    and all reach for the shell are three unattended turns competing over the
    same machine, and the whole point of the beta is that it does one obvious
    thing.
    """

    def __init__(self, director_for):
        self.director_for = director_for
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_now(self, automation: Automation) -> dict[str, Any]:
        async with self._lock:
            return await run_once(automation, director_for=self.director_for)

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(TICK_SECONDS)
                for automation in AutomationRepository().due():
                    async with self._lock:
                        # Re-read: it may have been switched off or already run
                        # by "run now" while this tick was waiting on the lock.
                        fresh = AutomationRepository().get(automation.id)
                        if fresh is None or not fresh.enabled:
                            continue
                        if parse_iso(fresh.next_run_at) > _now():
                            continue
                        log.info("running automation %s (%s)", fresh.id, fresh.name)
                        await run_once(fresh, director_for=self.director_for)
            except asyncio.CancelledError:
                raise
            except Exception:  # one bad tick must not end the runner
                log.exception("automation tick failed")
