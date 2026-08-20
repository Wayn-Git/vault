"""Long-term memory: extraction after a turn, recall before a later one.

The store, the service and the schema were written in an earlier session and
left unreachable -- no caller, no test. These cover the wiring as well as the
pieces: the acceptance case for Phase 9 is a fact stated in one conversation
being recalled, unprompted, in a different one.
"""

from __future__ import annotations

import hashlib

import pytest

from psok.agent.director import Director
from psok.db.repositories import ConversationRepository
from psok.memory import MemoryDiff, MemoryService, MemoryStore, parse_diff
from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel
from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.registry import ToolRegistry

DIMENSIONS = 16
EXTRACTION_MARKER = "You maintain a long-term memory"


class FakeEmbedder:
    """Deterministic hash vectors, so recall is testable without a model."""

    provider = "fake"
    model = "fake-embed"

    def __init__(self):
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vector(t) for t in texts]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.lower().encode()).digest()
        return [digest[i] / 255.0 for i in range(DIMENSIONS)]


class ScriptedModel:
    """Answers a turn, and answers the extractor with whatever diff is queued."""

    def __init__(self, answer: str = "noted", diff: str = '{"create": [], "supersede": []}'):
        self.answer = answer
        self.diff = diff
        self.extraction_calls = 0
        self.prompts: list[str] = []

    async def complete(self, messages, tools=None, params=None):
        system = messages[0].get("content") or ""
        self.prompts.append(system)
        if EXTRACTION_MARKER in system:
            self.extraction_calls += 1
            return ModelResponse(text=self.diff)
        return ModelResponse(text=self.answer)


@pytest.fixture
def scripted(monkeypatch):
    """Resolve every provider to one scripted model, in both director and service."""

    def install(model: ScriptedModel) -> ScriptedModel:
        import psok.agent.director as director_module

        monkeypatch.setattr(
            director_module,
            "resolve",
            lambda *a, **k: ResolvedModel("f", "f", model, Capabilities(streaming=False)),
        )
        monkeypatch.setattr("psok.retrieval.search.Embedder", lambda *a, **k: FakeEmbedder())
        monkeypatch.setattr("psok.retrieval.embeddings.Embedder", lambda *a, **k: FakeEmbedder())
        return model

    return install


def _director() -> Director:
    return Director(ToolRegistry(ConfirmationService(auto_approve)), retrieval=False)


async def _turn(director: Director, conversation_id: str, message: str) -> list:
    return [event async for event in director.run(conversation_id, message)]


# ------------------------------------------------------------- diff parsing


def test_a_plain_diff_is_read():
    diff = parse_diff('{"create": ["lives in Kigali"], "supersede": [3]}', known_ids={3})
    assert diff.create == ["lives in Kigali"]
    assert diff.supersede == [3]
    assert diff


def test_a_fenced_diff_is_read():
    diff = parse_diff('```json\n{"create": ["a"], "supersede": []}\n```')
    assert diff.create == ["a"]


def test_unparseable_output_costs_only_that_turn():
    """Extraction runs unattended after every turn; a model that wanders off the
    format must not raise into it."""
    assert not parse_diff("I think we should remember that...")
    assert not parse_diff("")
    assert not parse_diff("[1, 2, 3]")


def test_a_hallucinated_id_cannot_retire_a_real_memory():
    diff = parse_diff('{"create": [], "supersede": [99]}', known_ids={1, 2})
    assert diff.supersede == []


def test_an_empty_diff_is_falsy():
    assert not MemoryDiff()


# --------------------------------------------------------------------- store


async def test_applying_a_diff_creates_and_supersedes(db):
    service = MemoryService(embedder=FakeEmbedder())
    await service.apply(MemoryDiff(create=["prefers dark mode"]))

    held = service.store.live()
    assert [m.fact for m in held] == ["prefers dark mode"]

    await service.apply(MemoryDiff(create=["prefers light mode"], supersede=[held[0].id]))
    assert [m.fact for m in service.store.live()] == ["prefers light mode"]

    superseded = db.execute(
        "SELECT superseded_at FROM memories WHERE id = ?", (held[0].id,)
    ).fetchone()
    assert superseded["superseded_at"], "a retired fact is kept, not deleted"


async def test_superseding_a_fact_stops_it_being_recalled(db):
    service = MemoryService(embedder=FakeEmbedder())
    await service.apply(MemoryDiff(create=["works at Acme"]))
    fact_id = service.store.live()[0].id

    assert any("works at Acme" in m for m in await service.recall("where do I work"))
    assert service.store.supersede([fact_id]) == 1
    assert await service.recall("where do I work") == []
    assert service.store.supersede([fact_id]) == 0, "superseding twice is not a second retirement"


# -------------------------------------------------------------------- recall


async def test_recall_merges_both_paths_without_duplicates(db):
    """Recency surfaces what is current but unrelated; semantic surfaces what is
    related but possibly stale. A fact both paths return must appear once."""
    service = MemoryService(embedder=FakeEmbedder())
    await service.apply(MemoryDiff(create=["cycles to work", "allergic to peanuts"]))

    recalled = await service.recall("cycles to work")
    assert len(recalled) == len(set(recalled)) == 2


async def test_an_empty_store_never_reaches_the_embedder(db):
    """Recall runs on every turn. With nothing stored it must cost nothing --
    least of all a round trip to an embedding server that is usually not running
    before first use."""

    # A raising embedder would prove nothing: the semantic path catches, so the
    # call has to be counted rather than blocked.
    embedder = FakeEmbedder()
    assert await MemoryService(embedder=embedder).recall("anything") == []
    assert embedder.calls == 0, "an empty store must not embed the query"


async def test_recall_degrades_to_recency_when_the_embedder_is_down(db):
    service = MemoryService(embedder=FakeEmbedder())
    await service.apply(MemoryDiff(create=["drives a red car"]))

    class Broken(FakeEmbedder):
        async def embed_one(self, text):
            raise RuntimeError("embedding service down")

    recalled = await MemoryService(embedder=Broken()).recall("what car")
    assert any("red car" in m for m in recalled), "recency alone still recalls"


# --------------------------------------------------------------------- toggle


async def test_the_toggle_disables_recall_and_extraction(db, scripted):
    model = scripted(ScriptedModel(diff='{"create": ["hates onions"], "supersede": []}'))
    MemoryStore().set_enabled(False)

    cid = ConversationRepository().create("f", "f")
    await _turn(_director(), cid, "I hate onions")

    assert model.extraction_calls == 0, "extraction must not run while memory is off"
    assert MemoryStore().live() == []


async def test_a_conversation_can_opt_out_on_its_own(db, scripted):
    model = scripted(ScriptedModel(diff='{"create": ["a fact"], "supersede": []}'))
    private = ConversationRepository().create("f", "f")
    MemoryStore().set_enabled(False, conversation_id=private)

    await _turn(_director(), private, "something private")
    assert MemoryStore().live() == []

    ordinary = ConversationRepository().create("f", "f")
    await _turn(_director(), ordinary, "something ordinary")
    assert [m.fact for m in MemoryStore().live()] == ["a fact"]
    assert model.extraction_calls == 1


# ------------------------------------------------------- through the loop


async def test_a_fact_from_one_conversation_is_recalled_in_another(db, scripted):
    """Phase 9's acceptance criterion, end to end."""
    model = scripted(
        ScriptedModel(diff='{"create": ["the user is training for a marathon"], "supersede": []}')
    )

    first = ConversationRepository().create("f", "f")
    events = await _turn(_director(), first, "I am training for a marathon")

    remembered = [e for e in events if e.type == "memory"]
    assert remembered and remembered[0].data["created"] == [
        "the user is training for a marathon"
    ]
    assert [e.type for e in events].index("done") < [e.type for e in events].index("memory"), (
        "the turn finishes before extraction; the composer must not wait on it"
    )

    model.diff = '{"create": [], "supersede": []}'
    model.prompts.clear()
    second = ConversationRepository().create("f", "f")
    await _turn(_director(), second, "what should I eat this week?")

    turn_prompt = model.prompts[0]
    assert "<memories>" in turn_prompt
    assert "training for a marathon" in turn_prompt


async def test_extraction_failure_never_breaks_a_finished_turn(db, scripted):
    class Exploding(ScriptedModel):
        async def complete(self, messages, tools=None, params=None):
            system = messages[0].get("content") or ""
            if EXTRACTION_MARKER in system:
                raise RuntimeError("the extraction model is unreachable")
            return ModelResponse(text=self.answer)

    scripted(Exploding(answer="here is your answer"))
    cid = ConversationRepository().create("f", "f")
    events = await _turn(_director(), cid, "hello")

    kinds = [e.type for e in events]
    assert "error" not in kinds
    assert kinds[-1] == "done", "a failed extraction leaves the turn as it was: finished"


async def test_nothing_worth_remembering_emits_no_event(db, scripted):
    """Most exchanges change nothing, and an interface should not be told
    otherwise on every turn."""
    scripted(ScriptedModel())
    cid = ConversationRepository().create("f", "f")
    events = await _turn(_director(), cid, "what is 2 + 2?")

    assert [e.type for e in events if e.type == "memory"] == []
    assert MemoryStore().live() == []


async def test_a_configured_memory_model_is_used_instead_of_the_conversations(db, monkeypatch):
    """ai-runtime.md gives extraction its own row: it runs on every turn, so it
    wants a small cheap model rather than whichever one is answering."""
    import psok.agent.director as director_module
    from psok.config import paths

    paths().ensure()
    paths().providers_yaml.write_text(
        "providers:\n"
        "  - name: big\n"
        "    base_url: http://localhost:1/v1\n"
        "    default_model: big-model\n"
        "  - name: small\n"
        "    base_url: http://localhost:2/v1\n"
        "    default_model: small-model\n"
        "memory:\n"
        "  provider: small\n"
        "  model: small-model\n"
    )

    asked: list[str] = []

    def fake_resolve(provider, model=None):
        asked.append(f"{provider}:{model}")
        return ResolvedModel(provider, model or "", ScriptedModel(), Capabilities(streaming=False))

    monkeypatch.setattr(director_module, "resolve", fake_resolve)
    monkeypatch.setattr("psok.retrieval.embeddings.Embedder", lambda *a, **k: FakeEmbedder())

    cid = ConversationRepository().create("big", "big-model")
    await _turn(_director(), cid, "hello")

    assert "small:small-model" in asked, "the configured extraction model must be used"


async def test_extraction_falls_back_to_the_conversations_own_model(db, scripted):
    """A machine with one provider configured still gets memory, rather than
    memory silently doing nothing."""
    model = scripted(ScriptedModel(diff='{"create": ["fact"], "supersede": []}'))
    cid = ConversationRepository().create("f", "f")
    await _turn(_director(), cid, "hello")
    assert model.extraction_calls == 1


async def test_a_fact_already_held_is_not_stored_twice(db):
    """Duplicates are the extraction prompt's documented main failure mode, and
    a prompt is the wrong place to enforce that on its own."""
    service = MemoryService(embedder=FakeEmbedder())
    await service.apply(MemoryDiff(create=["the user is training for a marathon"]))
    applied = await service.apply(
        MemoryDiff(create=["The user is training for a marathon  ", "cycles to work"])
    )

    assert applied.create == ["cycles to work"], "only the genuinely new fact is applied"
    assert len(service.store.live()) == 2


async def test_a_correction_replaces_rather_than_being_refused(db):
    """Superseding runs first, so a diff that retires a fact and restates the
    corrected version is not blocked by its own predecessor."""
    service = MemoryService(embedder=FakeEmbedder())
    await service.apply(MemoryDiff(create=["works at Acme"]))
    old = service.store.live()[0].id

    applied = await service.apply(MemoryDiff(create=["works at Acme"], supersede=[old]))
    assert applied.create == ["works at Acme"]
    assert [m.fact for m in service.store.live()] == ["works at Acme"]
    assert len(service.store.live()) == 1


async def test_a_duplicate_is_not_reported_to_the_interface(db, scripted):
    """The event says what changed. Reporting a fact PSOK already held as
    'remembered' on every turn would be noise the user cannot act on."""
    model = scripted(ScriptedModel(diff='{"create": ["likes strong coffee"], "supersede": []}'))

    first = ConversationRepository().create("f", "f")
    await _turn(_director(), first, "I like strong coffee")

    second = ConversationRepository().create("f", "f")
    events = await _turn(_director(), second, "tell me again")

    assert model.extraction_calls == 2
    assert [e for e in events if e.type == "memory"] == [], "nothing changed, so nothing is said"
    assert len(MemoryStore().live()) == 1
