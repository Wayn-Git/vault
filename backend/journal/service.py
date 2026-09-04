"""Briefings and reviews: gathered by hand, written by a model, owned by the user.

The state machine is the part that matters, and it is not symmetric:

* **briefing** -- fires in the morning. Signals, then one model call. There is
  nothing to wait for, so it is complete when it is written.
* **daily** -- fires in the evening and **makes no model call**. It files the
  day's real figures and the check-in questions, and stops. The prose is written
  when the user answers, from their answers. A nightly review written before
  anyone has said anything is fabricated reflection: it can only be a rewording
  of the task list, dressed as insight.
* **weekly** -- fires on the configured day, over the week's figures *and* the
  week's daily entries. Its input already contains the user's own words, so
  writing it at fire time is honest.

One non-streaming `complete()` per entry, `tools=None`, exactly as
`MemoryService.extract` does it. Not an unattended agent turn: that runs behind
a gate that denies every confirmation, caps at three minutes, and would build
the figures from whichever tools it happened to call.

Nothing here may invent. With no provider configured, an entry still exists,
still carries the real signals, and says in `model_error` why there is no prose.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta

from backend.journal.prompts import CHECK_IN_QUESTIONS, PROMPT_FOR
from backend.journal.signals import Signals, gather, render
from backend.journal.store import JournalStore
from backend.runtime import availability
from backend.runtime.failures import FailureKind
from backend.runtime.registry import default_chain, resolve

log = logging.getLogger(__name__)

KINDS = ("briefing", "daily", "weekly")

#: A briefing is three paragraphs. A model that has not finished by now is not
#: going to say anything more useful for waiting.
GENERATION_TIMEOUT = 120.0
MAX_OUTPUT_TOKENS = 900

#: Daily entries pulled into a weekly rollup. Seven days, plus slack for a week
#: where something was regenerated.
MAX_WEEK_ENTRIES = 10

#: Providers tried after the first, for work nobody is waiting on. See _write.
BACKGROUND_FALLBACK_LINKS = 4


class JournalError(ValueError):
    """Something the caller can fix, phrased for whoever asked."""


def entry_as_dict(row) -> dict:
    data = dict(row)
    try:
        data["signals"] = json.loads(row["signals"]) if row["signals"] else {}
    except (ValueError, TypeError):
        data["signals"] = {}
    if row["kind"] == "daily":
        data["questions"] = list(CHECK_IN_QUESTIONS)
    return data


class JournalService:
    def __init__(self, store: JournalStore | None = None, client=None):
        # The client is injected so a test can run without a provider, and so
        # the same service backs the runner, the API and a manual regenerate.
        self.store = store or JournalStore()
        self._client = client

    # -- what the runner calls -------------------------------------------

    async def fire(self, kind: str, day: date) -> dict | None:
        """File today's entry, or return None because it is already filed."""
        _check_kind(kind)
        signals = await gather(day, span="week" if kind == "weekly" else "day")
        entry_id = self.store.claim(kind, day.isoformat(), signals.to_json())
        if entry_id is None:
            return None
        if kind == "daily":
            # Filed open, on purpose. The questions are the entry until the
            # user answers them.
            return entry_as_dict(self.store.get(entry_id))
        await self._write_into(entry_id, kind, signals, day)
        return entry_as_dict(self.store.get(entry_id))

    # -- what the interface calls ----------------------------------------

    async def generate(self, kind: str, day: date, *, force: bool = False) -> dict:
        """Write, or rewrite, one entry now."""
        _check_kind(kind)
        existing = self.store.by_date(kind, day.isoformat())
        if existing is not None and not force:
            return entry_as_dict(existing)

        signals = await gather(day, span="week" if kind == "weekly" else "day")
        if existing is None:
            entry_id = self.store.claim(kind, day.isoformat(), signals.to_json())
            if entry_id is None:  # a tick took it between the read and the write
                return entry_as_dict(self.store.by_date(kind, day.isoformat()))
        else:
            entry_id = existing["id"]
            self.store.update(entry_id, signals=signals.to_json())

        if kind == "daily":
            row = self.store.get(entry_id)
            if not (row["user_notes"] or "").strip():
                # Regenerating a review nobody has answered would write the same
                # invention the fire path deliberately refuses to.
                return entry_as_dict(row)
            return await self.answer(entry_id, row["user_notes"])

        await self._write_into(entry_id, kind, signals, day)
        return entry_as_dict(self.store.get(entry_id))

    async def answer(self, entry_id: int, user_notes: str) -> dict:
        """Store the user's own answers, then write the review from them."""
        row = self.store.get(entry_id)
        if row is None:
            raise JournalError(f"no journal entry {entry_id}")

        # Committed before the model call, always. A provider that hangs or
        # fails costs the prose; it must never cost what the user typed.
        self.store.update(entry_id, user_notes=user_notes)

        if not (user_notes or "").strip():
            self.store.update(entry_id, status="open", summary=None, model_error=None)
            return entry_as_dict(self.store.get(entry_id))

        signals = Signals.from_json(json.loads(row["signals"] or "{}"))
        await self._write_into(
            entry_id,
            row["kind"],
            signals,
            date.fromisoformat(row["entry_date"]),
            user_notes=user_notes,
        )
        return entry_as_dict(self.store.get(entry_id))

    def recent(self, *, kind: str | None = None, limit: int = 30) -> list[dict]:
        if kind:
            _check_kind(kind)
        return [entry_as_dict(row) for row in self.store.recent(kind=kind, limit=limit)]

    def today(self) -> dict[str, dict | None]:
        """The entries a dashboard needs: this morning's, and tonight's."""
        day = date.today().isoformat()
        briefing = self.store.by_date("briefing", day)
        review = self.store.by_date("daily", day)
        weekly = self.store.latest("weekly")
        return {
            "briefing": entry_as_dict(briefing) if briefing else None,
            "review": entry_as_dict(review) if review else None,
            "weekly": entry_as_dict(weekly) if weekly else None,
            "questions": list(CHECK_IN_QUESTIONS),
        }

    # -- the one model call ----------------------------------------------

    async def _write_into(
        self,
        entry_id: int,
        kind: str,
        signals: Signals,
        day: date,
        *,
        user_notes: str | None = None,
    ) -> None:
        summary, error, provider, model = await self._write(
            kind, signals, day, user_notes=user_notes
        )
        self.store.update(
            entry_id,
            summary=summary,
            model_error=error,
            model_provider=provider,
            model_name=model,
            status="complete" if summary else "open",
        )

    async def _write(
        self, kind: str, signals: Signals, day: date, *, user_notes: str | None = None
    ) -> tuple[str | None, str | None, str | None, str | None]:
        messages = [
            {"role": "system", "content": PROMPT_FOR[kind]},
            {"role": "user", "content": self._user_message(kind, signals, day, user_notes)},
        ]

        if self._client is not None:
            return await self._ask(self._client, messages, None, None)

        # A longer chain than a turn gets. `MAX_FALLBACK_LINKS` is two because a
        # person is waiting and proving the network is broken costs them
        # minutes; nobody is waiting on a briefing, and the cost of stopping
        # early is the whole entry. Still bounded, and still one attempt each.
        links = default_chain(limit=BACKGROUND_FALLBACK_LINKS)
        if not links:
            return (
                None,
                "no model is configured, so there is no summary -- the figures above are"
                " what actually happened. Add a provider in Settings to have this written up.",
                None,
                None,
            )

        # Walked rather than tried once, because nobody is watching at seven in
        # the morning: a local endpoint listed first in providers.yaml and not
        # running must not be the whole briefing on a machine with two working
        # providers behind it. Failures are recorded where the rest of the
        # system reads them, so a turn later in the day skips the same provider.
        last_error: str | None = None
        last_link = None
        for link in links:
            last_link = link
            try:
                model = resolve(link.provider, link.model)
            except Exception as exc:
                last_error = f"{link.provider} could not be resolved: {exc}"
                continue
            summary, error, provider, name = await self._ask(
                model.client, messages, link.provider, link.model
            )
            if summary:
                availability.record_success(link.provider)
                return summary, None, provider, name
            last_error = error

        # Name every provider that was asked, not just the one that happened to
        # fail last. "cerebras returned 404" reads as one broken provider; the
        # actual state is that three were tried and none answered, which is what
        # tells you to go and look at providers.yaml.
        tried = ", ".join(str(link) for link in links)
        return (
            None,
            f"none of the configured providers answered ({tried}). Last error: {last_error}",
            last_link.provider if last_link else None,
            last_link.model if last_link else None,
        )

    async def _ask(
        self, client, messages: list[dict], provider: str | None, model: str | None
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """One non-streaming call, with every failure turned into a sentence."""
        try:
            response = await asyncio.wait_for(
                client.complete(messages, tools=None), timeout=GENERATION_TIMEOUT
            )
        except TimeoutError:
            late = f"{provider or 'the model'} did not answer within {GENERATION_TIMEOUT:.0f}s"
            if provider:
                availability.record_failure(provider, FailureKind.RETRYABLE, late)
            return None, late, provider, model
        except Exception as exc:
            log.warning("journal generation failed on %s: %s", provider or "the model", exc)
            if provider:
                kind = getattr(exc, "kind", FailureKind.RETRYABLE)
                availability.record_failure(provider, kind, str(exc))
            return None, f"{provider or 'the model'} could not be reached: {exc}", provider, model

        text = (response.text or "").strip()
        if not text:
            return None, f"{provider or 'the model'} returned nothing", provider, model
        return text, None, provider, model

    def _user_message(
        self, kind: str, signals: Signals, day: date, user_notes: str | None
    ) -> str:
        parts = [f"<signals>\n{render(signals)}\n</signals>"]
        if user_notes:
            parts.append(f"<answers>\n{user_notes.strip()}\n</answers>")
        if kind == "weekly":
            parts.append(f"<entries>\n{self._week_entries(day)}\n</entries>")
        return "\n\n".join(parts)

    def _week_entries(self, day: date) -> str:
        """This week's daily reviews, in the user's words where they wrote any."""
        start = day - timedelta(days=day.weekday())
        rows = self.store.between(
            start.isoformat(), day.isoformat(), kind="daily"
        )[:MAX_WEEK_ENTRIES]
        if not rows:
            return "(no daily reviews were written this week)"
        blocks = []
        for row in rows:
            parts = [f"[{row['entry_date']}]"]
            if row["user_notes"]:
                parts.append(f"they wrote: {row['user_notes'].strip()}")
            if row["summary"]:
                parts.append(f"written up as: {row['summary'].strip()}")
            if len(parts) == 1:
                parts.append("(filed, not answered)")
            blocks.append("\n".join(parts))
        return "\n\n".join(blocks)

def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise JournalError(f"unknown kind '{kind}'. One of: {', '.join(KINDS)}")
