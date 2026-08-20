"""Long-term memory: extraction after a turn, recall before one.

The two-tier design taken from Khoj (docs/research/khoj.md). Tier one is the
verbatim transcript, which the message table already holds. Tier two is this: a
compact, model-curated set of standing facts, updated by a structured
create/supersede diff rather than by appending everything the user ever said.

Curation is the point. A store that only ever grows becomes noise, and noise in
the system prompt is worse than an empty block -- it costs budget on every turn
and dilutes what actually matters.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from psok.memory.store import Memory, MemoryStore

log = logging.getLogger(__name__)

# How much of the store is offered to the extractor and to the prompt. Both are
# caps on prompt budget, not on how much can be stored.
MAX_FACTS_IN_PROMPT = 30
RECENCY_DAYS = 30
RECENCY_LIMIT = 10
SEMANTIC_LIMIT = 10

EXTRACTION_PROMPT = """\
You maintain a long-term memory of standing facts about one user.

You will be given the facts you already hold and the latest exchange. Decide what
should change. Reply with JSON and nothing else:

{"create": ["a new fact", ...], "supersede": [<id of a fact that is now wrong>, ...]}

Rules:
- Record only durable facts about the user: preferences, identity, ongoing
  projects, relationships, constraints, decisions they have made.
- Do not record the content of the conversation itself, questions they asked,
  one-off requests, or anything you inferred rather than were told.
- Supersede a fact when the exchange contradicts or updates it. Pair the
  supersede with a create carrying the corrected version.
- Do not restate a fact you already hold. Duplicates are the main failure mode.
- Most exchanges change nothing. {"create": [], "supersede": []} is the right
  answer far more often than not, and is always better than a weak guess."""


@dataclass
class MemoryDiff:
    create: list[str] = field(default_factory=list)
    supersede: list[int] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.create or self.supersede)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_diff(text: str, *, known_ids: set[int] | None = None) -> MemoryDiff:
    """Read the model's reply into a diff, discarding anything malformed.

    Extraction runs unattended after every turn, so a model that wanders off the
    format must cost nothing more than that turn's facts. Ids that do not exist
    are dropped rather than trusted -- a hallucinated id would otherwise retire
    a real memory.
    """
    if not text:
        return MemoryDiff()

    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1)
    else:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        payload = json.loads(candidate)
    except (ValueError, TypeError):
        log.warning("memory extraction returned unparseable output: %r", text[:200])
        return MemoryDiff()
    if not isinstance(payload, dict):
        return MemoryDiff()

    create = [
        fact.strip()
        for fact in payload.get("create") or []
        if isinstance(fact, str) and fact.strip()
    ]

    supersede: list[int] = []
    for raw in payload.get("supersede") or []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if known_ids is None or value in known_ids:
            supersede.append(value)

    return MemoryDiff(create=create, supersede=supersede)


def render(facts: list[Memory]) -> list[str]:
    """Facts as the prompt sees them, id included so the model can supersede one."""
    return [f"[{m.id}] {m.fact}" for m in facts]


class MemoryService:
    def __init__(self, store: MemoryStore | None = None, embedder=None):
        self.store = store or MemoryStore()
        self._embedder = embedder

    # ------------------------------------------------------------ recall

    async def recall(self, query: str, conversation_id: str | None = None) -> list[str]:
        """Recency plus semantic similarity, merged and deduplicated by id.

        Two paths because they fail in opposite directions: recency surfaces
        what is current but unrelated, semantic surfaces what is related but
        possibly stale. Neither alone is recall.

        Semantic search is best-effort. With no embedder configured, or none
        reachable, this degrades to recency rather than returning nothing --
        memory that needs a running embedding server to work at all would be
        off by default on most machines.
        """
        if not self.store.is_enabled(conversation_id):
            return []

        by_id: dict[int, Memory] = {m.id: m for m in self.store.recent(RECENCY_DAYS, RECENCY_LIMIT)}

        for memory in self.store.get_many(await self._semantic_ids(query)):
            by_id.setdefault(memory.id, memory)

        ordered = sorted(by_id.values(), key=lambda m: (m.created_at, m.id), reverse=True)
        return render(ordered[:MAX_FACTS_IN_PROMPT])

    async def _semantic_ids(self, query: str) -> list[int]:
        if not query.strip():
            return []
        embedder = self._resolve_embedder()
        if embedder is None:
            return []
        try:
            vector = await embedder.embed_one(query)
        except Exception as exc:
            log.debug("memory semantic recall unavailable: %s", exc)
            return []
        return self.store.search(vector, SEMANTIC_LIMIT)

    def _resolve_embedder(self):
        """Whichever model already embedded the memories, or the default."""
        if self._embedder is not None:
            return self._embedder
        from psok.retrieval.embeddings import Embedder

        pinned = self.store.embedding_model()
        return Embedder(*pinned) if pinned else Embedder()

    # ---------------------------------------------------------- extraction

    async def extract(
        self,
        conversation_id: str,
        user_message: str,
        assistant_text: str,
        client,
    ) -> MemoryDiff:
        """One model call after a turn, producing a diff that is then applied.

        Returns the diff that was actually applied, which is empty whenever the
        model declined, wandered off the format, or memory is switched off.
        """
        if not self.store.is_enabled(conversation_id):
            return MemoryDiff()
        if not assistant_text.strip():
            return MemoryDiff()

        existing = self.store.live(MAX_FACTS_IN_PROMPT)
        known = "\n".join(render(existing)) or "(none yet)"
        exchange = f"User: {user_message}\nAssistant: {assistant_text}"

        response = await client.complete(
            [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {
                    "role": "user",
                    "content": f"<facts>\n{known}\n</facts>\n\n<exchange>\n{exchange}\n</exchange>",
                },
            ],
            tools=None,
        )

        diff = parse_diff(response.text or "", known_ids={m.id for m in existing})
        await self.apply(diff, conversation_id)
        return diff

    async def apply(self, diff: MemoryDiff, conversation_id: str | None = None) -> None:
        """Supersede first, so a correction never briefly reads as both facts."""
        self.store.supersede(diff.supersede)
        if not diff.create:
            return

        embedder = self._resolve_embedder()
        vectors: list[list[float]] = []
        if embedder is not None:
            try:
                vectors = await embedder.embed(diff.create)
            except Exception as exc:
                # A fact worth keeping is worth keeping unsearchable. Recency
                # recall still reaches it; the vector can be backfilled later.
                log.debug("could not embed new memories: %s", exc)

        for position, fact in enumerate(diff.create):
            memory_id = self.store.add(fact, conversation_id)
            if position < len(vectors):
                self.store.index(memory_id, vectors[position])
                self.store.record_embedding_model(embedder.provider, embedder.model)
