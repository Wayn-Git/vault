"""Chunking, incremental indexing, hybrid search.

A deterministic fake embedder keeps these offline. The point of the fake is that
indexing and fusion logic are testable without a model; the quality of real
embeddings is a separate question, covered by the live suite.
"""

from __future__ import annotations

import hashlib

import pytest

from backend.retrieval import store
from backend.retrieval.chunking import chunk_markdown, estimate_tokens
from backend.retrieval.indexer import Indexer, discover
from backend.retrieval.search import SearchService
from backend.tools.base import ToolContext

DIMENSIONS = 16


class FakeEmbedder:
    """Hash-based vectors: deterministic, and identical text embeds identically."""

    # Mirrors the real Embedder's contract: the indexer records which model built
    # the index so queries are embedded by that same model.
    provider = "fake"
    model = "fake-embed"

    def __init__(self):
        self.calls = 0
        self.texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts.extend(texts)
        return [self._vector(t) for t in texts]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.lower().encode()).digest()
        return [digest[i] / 255.0 for i in range(DIMENSIONS)]


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "ml.md").write_text(
        "# Machine Learning\n\n"
        "## Assignment\n"
        "Implement gradient descent from scratch before the deadline.\n\n"
        "## Lectures\n"
        "Backpropagation applies the chain rule.\n"
    )
    (root / "notes" / "infra.md").write_text(
        "# Infrastructure\n\n## Deploy\nError code E4471 means the probe failed.\n"
    )
    (root / "notes" / ".hidden.md").write_text("secret")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.md").write_text("dependency noise")
    return root


# ------------------------------------------------------------------ chunking


def test_headings_become_the_chunk_path():
    chunks = chunk_markdown("# Top\n\nintro\n\n## Section\n\nbody text\n")
    paths = [c.heading_path for c in chunks]
    assert "Top" in paths
    assert "Top > Section" in paths


def test_heading_path_is_prefixed_into_the_content():
    """A chunk lifted out of its section must carry its context with it."""
    chunks = chunk_markdown("# Notes\n\n## Tuesday\n\nStandup at ten.\n")
    section = next(c for c in chunks if c.heading_path == "Notes > Tuesday")
    assert section.content.startswith("Notes > Tuesday")
    assert "Standup at ten." in section.content


def test_oversized_sections_are_split():
    body = " ".join(f"word{i}" for i in range(4000))
    chunks = chunk_markdown(f"# Big\n\n{body}", max_tokens=100)
    assert len(chunks) > 1
    assert all(c.token_count <= 200 for c in chunks)


def test_unbroken_text_is_still_split():
    """No separator to split on must not produce one enormous chunk."""
    chunks = chunk_markdown("x" * 5000, max_tokens=50)
    assert len(chunks) > 1


def test_empty_input_yields_nothing():
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n\n  ") == []


def test_identical_content_hashes_identically():
    a = chunk_markdown("# T\n\nsame body")[0]
    b = chunk_markdown("# T\n\nsame body")[0]
    assert a.content_hash == b.content_hash


def test_token_estimate_is_positive():
    assert estimate_tokens("hello world") >= 1


# ----------------------------------------------------------------- discovery


def test_discovery_skips_hidden_and_vendored_files(vault):
    found = {p.name for p in discover(vault)}
    assert {"ml.md", "infra.md"} <= found
    assert ".hidden.md" not in found
    assert "junk.md" not in found, "node_modules must not be indexed"


# ------------------------------------------------------------------ indexing


async def test_indexing_then_reindexing_does_no_embedding_work(db, vault):
    embedder = FakeEmbedder()
    indexer = Indexer(embedder, conn=db)

    first = await indexer.index_vault(vault)
    assert first.indexed == 2
    assert first.chunks_added > 0

    calls_after_first = embedder.calls
    second = await indexer.index_vault(vault)

    assert second.indexed == 0
    assert second.unchanged == 2
    assert second.chunks_added == 0
    assert embedder.calls == calls_after_first, "unchanged files must not re-embed"


async def test_editing_one_file_reembeds_only_its_changed_chunks(db, vault):
    embedder = FakeEmbedder()
    indexer = Indexer(embedder, conn=db)
    await indexer.index_vault(vault)

    (vault / "notes" / "infra.md").write_text(
        "# Infrastructure\n\n## Deploy\nError code E9999 now.\n"
    )
    embedder.texts.clear()
    report = await indexer.index_vault(vault)

    assert report.indexed == 1 and report.unchanged == 1
    assert report.chunks_added == 1 and report.chunks_deleted == 1
    assert all("E9999" in t or "Deploy" in t for t in embedder.texts)


async def test_deleted_files_are_pruned(db, vault):
    indexer = Indexer(FakeEmbedder(), conn=db)
    await indexer.index_vault(vault)
    before = indexer.stats()["documents"]

    (vault / "notes" / "infra.md").unlink()
    report = await indexer.index_vault(vault)

    assert report.removed == 1
    assert indexer.stats()["documents"] == before - 1


async def test_marking_stale_forces_a_reindex(db, vault):
    """PSOK's own file edits invalidate the index immediately."""
    indexer = Indexer(FakeEmbedder(), conn=db)
    await indexer.index_vault(vault)

    target = vault / "notes" / "ml.md"
    indexer.mark_stale(target)
    report = await indexer.index_vault(vault)
    assert report.indexed == 1, "a stale document must be re-examined"


async def test_write_file_tool_invalidates_the_index(db, vault):
    from backend.tools.builtin.filesystem import write_file

    indexer = Indexer(FakeEmbedder(), conn=db)
    await indexer.index_vault(vault)

    await write_file(
        {"path": str(vault / "notes" / "ml.md"), "content": "# Machine Learning\n\nrewritten\n"},
        ToolContext(workspace_root=str(vault)),
    )
    row = db.execute(
        "SELECT stale FROM documents WHERE path = ?", (str(vault / "notes" / "ml.md"),)
    ).fetchone()
    assert row["stale"] == 1


async def test_edit_file_tool_invalidates_the_index(db, vault):
    """write_file and delete_file marked the document stale; edit_file did not,
    so the most common way the agent changes a file left the index claiming
    content that is no longer on disk -- until an unrelated full re-scan."""
    from backend.tools.builtin.filesystem import edit_file

    await Indexer(FakeEmbedder(), conn=db).index_vault(vault)

    result = await edit_file(
        {
            "path": str(vault / "notes" / "ml.md"),
            "old_string": "gradient descent",
            "new_string": "stochastic gradient descent",
        },
        ToolContext(workspace_root=str(vault)),
    )
    assert not result.is_error

    row = db.execute(
        "SELECT stale FROM documents WHERE path = ?", (str(vault / "notes" / "ml.md"),)
    ).fetchone()
    assert row["stale"] == 1


# -------------------------------------------------------------------- search


async def test_keyword_search_finds_an_exact_term(db, vault):
    """The case dense vectors are worst at, and why FTS5 is not optional."""
    embedder = FakeEmbedder()
    await Indexer(embedder, conn=db).index_vault(vault)

    hits = await SearchService(embedder, conn=db).search("E4471", limit=3)
    assert hits, "an exact error code must be findable"
    assert "infra.md" in hits[0].path


async def test_search_returns_nothing_for_an_empty_index(db):
    assert await SearchService(FakeEmbedder(), conn=db).search("anything") == []


async def test_blank_query_is_rejected(db):
    assert await SearchService(FakeEmbedder(), conn=db).search("   ") == []


async def test_path_filter_narrows_results(db, vault):
    embedder = FakeEmbedder()
    await Indexer(embedder, conn=db).index_vault(vault)
    service = SearchService(embedder, conn=db)

    hits = await service.search("Error deploy probe", limit=10, path_glob="*infra*")
    assert all("infra" in h.path for h in hits)


async def test_context_assembly_respects_its_budget(db, vault):
    embedder = FakeEmbedder()
    await Indexer(embedder, conn=db).index_vault(vault)

    context = await SearchService(embedder, conn=db).context_for("gradient", budget_chars=120)
    assert len(context) <= 200


async def test_search_survives_a_broken_embedder(db, vault):
    """Semantic search failing must degrade to keywords, not break the tool."""
    await Indexer(FakeEmbedder(), conn=db).index_vault(vault)

    class BrokenEmbedder(FakeEmbedder):
        async def embed_one(self, text):
            raise RuntimeError("embedding service down")

    hits = await SearchService(BrokenEmbedder(), conn=db).search("E4471", limit=3)
    assert hits, "keyword results should still come back"


# ---------------------------------------------------------------- fusion math


def test_rank_fusion_rewards_agreement_between_indexes():
    keyword = [(1, 0.9), (2, 0.5)]
    vector = [(2, 0.1), (3, 0.4)]
    fused = dict(store.reciprocal_rank_fusion([keyword, vector]))
    # 2 appears in both lists, so it should outrank items found by only one.
    assert fused[2] > fused[1]
    assert fused[2] > fused[3]


def test_fusion_uses_rank_not_raw_score():
    """Cosine distance and BM25 are unrelated scales; blending them would be wrong."""
    a = [(1, 1000.0)]
    b = [(2, 0.0001)]
    fused = dict(store.reciprocal_rank_fusion([a, b]))
    assert fused[1] == pytest.approx(fused[2]), "equal rank means equal contribution"


def test_fts_query_sanitization_survives_punctuation():
    """Raw user text reaches FTS5, whose operators would otherwise be a syntax error."""
    assert (
        store._sanitize_fts_query('what is "E4471"? (urgent)')
        == '"what" OR "is" OR "E4471" OR "urgent"'
    )
    assert store._sanitize_fts_query("!!!") == ""


# ----------------------------------------------------------------- the tools


async def test_search_tool_reports_an_empty_index_helpfully(db):
    from backend.tools.builtin.documents import search_documents

    result = await search_documents({"query": "anything"}, ToolContext())
    assert not result.is_error
    assert "psok index" in result.content, "tell the user how to fix it"


async def test_search_tool_needs_a_query(db):
    from backend.tools.builtin.documents import search_documents

    assert (await search_documents({}, ToolContext())).is_error


async def test_search_tool_is_registered_and_low_risk(db):
    from backend.tools.base import RiskLevel
    from backend.tools.registry import build_default_registry

    tool = build_default_registry().get("search_documents")
    assert tool is not None
    assert tool.risk is RiskLevel.LOW, "reading indexed notes should not prompt"


# --------------------------------------------------------------------------
# regression: CPython reuses id() for sequential connections, so caching
# per-connection state by id() hands a fresh connection a dead one's flag.
# When that flag wrongly said "loaded", creating the vec0 table raised and
# aborted indexing entirely -- the document silently never got indexed.
# --------------------------------------------------------------------------


def test_extension_state_is_not_cached_by_connection_id():
    import sqlite3

    from backend.db.connection import connect, migrate

    ids = set()
    for _ in range(4):
        conn = sqlite3.connect(":memory:")
        ids.add(id(conn))
        conn.close()
    if len(ids) > 1:
        pytest.skip("this interpreter did not reuse connection ids")

    # A connection that never had the extension loaded must report honestly.
    plain = sqlite3.connect(":memory:")
    try:
        assert store._is_loaded(plain) is False
    finally:
        plain.close()
    assert connect and migrate  # keep the import meaningful


async def test_indexing_survives_a_fresh_connection_after_others_closed(tmp_path, psok_home):
    """The exact shape of the id-reuse bug: index, drop the connection, index again."""
    from backend.db import connection as connection_module

    root = tmp_path / "v"
    root.mkdir()
    (root / "a.md").write_text("# A\n\nUnique term ZQ7788 lives here.\n")

    conn = connection_module.get_connection()
    await Indexer(FakeEmbedder(), conn=conn).index_vault(root)
    assert store.search_keywords(conn, "ZQ7788", 5), "first pass should index"

    connection_module.reset_connection()
    fresh = connection_module.get_connection()

    (root / "b.md").write_text("# B\n\nAnother unique term QX9911 here.\n")
    report = await Indexer(FakeEmbedder(), conn=fresh).index_vault(root)

    assert not report.errors, f"indexing must not error on a fresh connection: {report.errors}"
    assert store.search_keywords(fresh, "QX9911", 5), "the new document must be searchable"


def test_vector_index_failure_still_leaves_keyword_search_working(db, monkeypatch):
    """Losing semantic search degrades results; losing FTS loses the document."""
    monkeypatch.setattr(store, "load_extension", lambda conn: False)
    store.ensure_indexes(db, 16)

    store.index_chunk(db, 1, "findable text about kangaroos", None, None)
    db.commit()
    assert store.search_keywords(db, "kangaroos", 5)


async def test_search_uses_the_model_that_built_the_index(db, vault):
    """Querying with a different model than indexed returns nonsense, not an error."""
    embedder = FakeEmbedder()
    await Indexer(embedder, conn=db).index_vault(vault)

    assert store.indexed_embedding_model(db) == ("fake", "fake-embed")

    service = SearchService(conn=db)  # no embedder passed: must adopt the recorded one
    assert service.embedder.provider == "fake"
    assert service.embedder.model == "fake-embed"


def test_search_falls_back_to_the_default_when_nothing_is_indexed(db):
    service = SearchService(conn=db)
    assert service.embedder.provider == "ollama"


# ------------------------------------------------- retrieval inside the loop


class _CapturingClient:
    """A provider that answers once and keeps the prompt it was given."""

    def __init__(self):
        self.system_prompts: list[str] = []

    async def complete(self, messages, tools=None, params=None):
        from backend.runtime.types import ModelResponse

        self.system_prompts.append(messages[0]["content"])
        return ModelResponse(text="answered")


def _scripted_director(monkeypatch, client):
    import backend.agent.director as director_module
    from backend.agent.director import Director
    from backend.runtime.types import Capabilities, ResolvedModel
    from backend.security.confirmation import ConfirmationService
    from backend.tools.registry import ToolRegistry

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", client, Capabilities(streaming=False)),
    )
    return Director(ToolRegistry(ConfirmationService()))


async def test_a_turn_injects_indexed_context_into_the_system_prompt(db, vault, monkeypatch):
    """context_for() existed, was tested, and was documented as pre-fetched into
    the prompt -- but the loop never called it, so the only way documents ever
    reached the model was the model deciding to search for them itself."""
    from backend.db.repositories import ConversationRepository

    embedder = FakeEmbedder()
    await Indexer(embedder, conn=db).index_vault(vault)
    monkeypatch.setattr("backend.retrieval.search.Embedder", lambda *a, **k: embedder)

    client = _CapturingClient()
    director = _scripted_director(monkeypatch, client)
    cid = ConversationRepository().create("f", "f")

    async for _ in director.run(cid, "what did I write about gradient descent?"):
        pass

    prompt = client.system_prompts[0]
    assert "<retrieved_context>" in prompt
    assert "gradient descent" in prompt


async def test_an_empty_index_costs_the_turn_no_retrieval_work(db, monkeypatch):
    """Skipped before the embedder is ever constructed: a user who has never run
    `psok index` must not pay a round trip to an embedding server on every turn."""
    from backend.db.repositories import ConversationRepository

    def explode(*a, **k):
        raise AssertionError("no embedder should be built for an empty index")

    monkeypatch.setattr("backend.retrieval.search.Embedder", explode)

    client = _CapturingClient()
    director = _scripted_director(monkeypatch, client)
    cid = ConversationRepository().create("f", "f")

    async for _ in director.run(cid, "anything at all"):
        pass

    assert "<retrieved_context>" not in client.system_prompts[0]


# -- indexing without an embedder, and telling sources apart ------------------


class _Dead:
    """An embedding server that is not running, which is the common case."""

    provider, model = "ollama", "nomic-embed-text"

    async def embed(self, texts):
        from backend.retrieval.embeddings import EmbeddingError

        raise EmbeddingError("could not reach Ollama at http://localhost:11434")


class _Fake:
    provider, model = "ollama", "nomic-embed-text"

    async def embed(self, texts):
        return [[float(len(t) % 5), 1.0, 0.25] for t in texts]

    async def embed_one(self, text):
        return (await self.embed([text]))[0]


async def test_the_keyword_index_does_not_depend_on_an_embedder(db, workspace):
    """`chunks_fts` used to be created only inside `ensure_indexes`, which the
    indexer only called once vectors had come back -- so the half of search that
    is supposed to survive a missing embedder had no table to write into.

    Mutation check: make `ensure_keyword_index` conditional on `vectors`.
    """
    from backend.retrieval.indexer import Indexer
    from backend.retrieval.search import SearchService

    note = workspace / "note.md"
    note.write_text("# Note\n\nAttention residue is the cost of switching.\n")

    await Indexer(embedder=_Dead()).index_file(note, require_embeddings=False)

    hits = await SearchService(embedder=_Dead()).search("attention residue")
    assert [h.label for h in hits] == ["note.md > Note"]


async def test_a_vault_index_still_fails_loudly_without_an_embedder(db, workspace):
    """The tolerant path is opt-in. A broken embedder affects every file in a
    vault, so indexing one should fail once, loudly, rather than quietly build
    half an index nobody knows is half.

    Mutation check: default `require_embeddings` to False.
    """
    from backend.retrieval.embeddings import EmbeddingError
    from backend.retrieval.indexer import Indexer

    (workspace / "note.md").write_text("# Note\n\nSomething worth indexing.\n")

    with pytest.raises(EmbeddingError):
        await Indexer(embedder=_Dead()).index_vault(workspace)


async def test_search_can_be_narrowed_to_one_source(db, workspace):
    """Vault notes and captured pages share one index. "What have I read about
    X" is a different question from "what is in my notes about X"."""
    from backend.retrieval.indexer import Indexer
    from backend.retrieval.search import SearchService

    note = workspace / "note.md"
    note.write_text("# Note\n\nAttention residue is the cost of switching.\n")
    saved = workspace / "saved.md"
    saved.write_text("# Deep Work\n\nAttention residue is the cost of switching.\n")

    indexer = Indexer(embedder=_Fake())
    await indexer.index_file(note)
    await indexer.index_file(saved, source="library", title="Deep Work")

    everything = await SearchService(embedder=_Fake()).search("attention residue")
    assert len(everything) == 2

    library_only = await SearchService(embedder=_Fake()).search(
        "attention residue", source="library"
    )
    assert [h.label for h in library_only] == ["Deep Work"]
