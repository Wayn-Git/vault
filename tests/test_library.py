"""The library: capturing what was read, and finding it again.

The rule under every one of these is the same. A capture that goes partly wrong
-- a paywall, a dead link, an embedding server that is not running -- loses some
of what the item could have been, and must never lose the fact that it was read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.db.connection import get_connection
from backend.library.service import LibraryService
from backend.library.store import LibraryStore
from backend.mcp.ssrf import UnsafeURL
from backend.retrieval.embeddings import EmbeddingError
from backend.retrieval.indexer import Indexer
from backend.retrieval.search import SearchService
from backend.web.reader import FetchedPage, FetchError

ARTICLE = "Attention residue is the cost of switching between tasks. " * 20


class DeadEmbedder:
    """An embedding server that is not running, which is the common case."""

    provider, model = "ollama", "nomic-embed-text"

    async def embed(self, texts):
        raise EmbeddingError("could not reach Ollama at http://localhost:11434")


class FakeEmbedder:
    provider, model = "ollama", "nomic-embed-text"

    async def embed(self, texts):
        return [[float(len(t) % 7), 1.0, 0.5] for t in texts]

    async def embed_one(self, text):
        return (await self.embed([text]))[0]


def page(**over):
    base = dict(
        url="https://calnewport.com/deep-work",
        final_url="https://calnewport.com/deep-work",
        title="Deep Work",
        text=ARTICLE,
        site="calnewport.com",
        author="Cal Newport",
        published_on="2016-01-05",
        content_type="text/html",
    )
    base.update(over)
    return FetchedPage(**base)


def service(*, embedder=None, fetcher=None):
    async def default_fetch(url, **kwargs):
        return page(url=url, final_url=url)

    return LibraryService(
        indexer=Indexer(embedder=embedder or FakeEmbedder()),
        fetcher=fetcher or default_fetch,
    )


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def offline(monkeypatch):
    """Let the fake hosts through the SSRF guard without a DNS lookup.

    `check_url` resolves the host, so a made-up domain fails as "cannot resolve"
    -- correct behaviour, and not what these tests are about. The tests that are
    about the guard use a literal address and keep the real one.
    """
    async def allow(url, **kwargs):
        return None

    monkeypatch.setattr("backend.library.service.check_url_async", allow)


async def test_capture_writes_a_real_file_and_indexes_it(db, offline, psok_home):
    """The text is a file on disk, not a row pretending to be one.

    PSOK stores an index that points at the filesystem and treats the file as
    the source of truth (ADR-0004). A synthetic path would leave `mtime` and
    `size_bytes` NULL and break that for the sake of skipping one write.

    Mutation check: store the text in `library_items` and give `documents` a
    made-up path.
    """
    captured = await service().capture_url("https://calnewport.com/deep-work")

    path = Path(captured.item["text_path"])
    assert path.is_file() and path.parent == psok_home / "library"
    assert captured.item["title"] == "Deep Work"
    assert captured.item["author"] == "Cal Newport"
    assert captured.item["published_on"] == "2016-01-05"

    row = get_connection().execute(
        "SELECT source, path, title, mtime, size_bytes FROM documents"
    ).fetchone()
    assert row["source"] == "library"
    assert row["path"] == str(path.resolve())
    assert row["mtime"] is not None and row["size_bytes"] > 0


async def test_a_capture_with_no_embedder_is_still_findable(db, offline):
    """The bug this guards against was invisible until the library existed:
    `chunks_fts` was only created as a side effect of `ensure_indexes`, which
    the indexer only called when the embedder had returned vectors. So the
    keyword half -- the half that is meant to survive a missing embedder --
    had no table to write into.

    Mutation check: call `ensure_keyword_index` only when `vectors` is truthy.
    """
    captured = await service(embedder=DeadEmbedder()).capture_url("https://example.com/a")

    assert captured.item["indexed"] is True
    hits = await SearchService(embedder=DeadEmbedder()).search("attention residue")
    assert [h.label for h in hits] == ["Deep Work"]


async def test_a_library_hit_is_labelled_by_its_title(db, offline):
    """A saved article has no filename the user chose, so `000001-deep-work.md`
    is not what it is called. Its title is."""
    await service().capture_url("https://example.com/a")

    hits = await SearchService(embedder=FakeEmbedder()).search("attention", source="library")
    assert hits and hits[0].label == "Deep Work"
    assert hits[0].source == "library"


async def test_a_vault_hit_keeps_its_filename(db, workspace):
    """The guard on the label change. `documents.title` is `path.stem` for vault
    files, so preferring the title unconditionally would rename every existing
    hit from `notes.md` to `notes`.

    Mutation check: drop the `source != "vault"` condition from `SearchHit.label`.
    """
    note = workspace / "notes.md"
    note.write_text("# Notes\n\nAttention residue is real.\n")
    await Indexer(embedder=FakeEmbedder()).index_vault(workspace)

    hits = await SearchService(embedder=FakeEmbedder()).search("attention residue")
    assert [h.label for h in hits] == ["notes.md > Notes"]


async def test_a_private_address_is_refused_and_writes_no_row(db):
    """The same guard the MCP transports use. A refused capture must not leave
    a half-item behind saying something was logged."""
    from backend.library.service import LibraryError

    with pytest.raises(LibraryError):
        await service().capture_url("http://127.0.0.1:8000/admin")
    assert LibraryStore().list() == []


async def test_a_redirect_to_a_private_address_is_refused(db, offline):
    """The pre-existing hole this change closes: `fetch_url` validated the URL
    it was handed and then followed redirects with no further checks, so a
    public address answering `302 Location: http://169.254.169.254/` was
    fetched and handed back.

    Mutation check: pass `follow_redirects=True` in `fetch_readable` and drop
    the per-hop `check_url_async`.
    """
    from backend.library.service import LibraryError

    async def redirects_inward(url, **kwargs):
        raise UnsafeURL("'169.254.169.254' resolves to a private or loopback address.")

    with pytest.raises(LibraryError, match="private or loopback"):
        await service(fetcher=redirects_inward).capture_url("https://example.com/redirect")
    assert LibraryStore().list() == []


async def test_repasting_a_link_returns_what_is_already_there(db, offline):
    """Re-pasting a link is how you land here, and a duplicate row plus a second
    fetch is not what that meant."""
    svc = service()
    first = await svc.capture_url("https://example.com/a")
    again = await svc.capture_url("https://example.com/a")

    assert again.already_logged is True
    assert again.item["id"] == first.item["id"]
    assert len(LibraryStore().list()) == 1


async def test_a_page_that_gives_up_no_text_is_still_logged(db, offline):
    """A paywall loses the text. It does not lose the fact that you read it --
    and the item says which of those happened rather than looking like a bug.

    Mutation check: raise instead of writing the row when the fetch fails.
    """
    async def refuses(url, **kwargs):
        raise FetchError("https://paywalled.example returned HTTP 403")

    captured = await service(fetcher=refuses).capture_url("https://paywalled.example/x")

    assert captured.item["id"]
    assert captured.item["indexed"] is False
    assert "403" in captured.item["capture_note"]


async def test_a_book_logged_by_hand_is_searchable_through_its_notes(db):
    """There is no page to fetch for a book, so what you wrote about it is the
    only searchable thing there is."""
    captured = await service().log_manual(
        title="Deep Work",
        kind="book",
        author="Cal Newport",
        notes="Attention residue is the cost of switching. Batch shallow work.",
    )
    assert captured.item["capture_note"] is None

    found = await service().search("attention residue")
    assert [item["title"] for item in found] == ["Deep Work"]


async def test_deleting_removes_the_text_the_chunks_and_the_index(db, offline):
    """A removed item leaves nothing searchable behind, or the next query
    returns a passage from something that is no longer there."""
    svc = service()
    captured = await svc.capture_url("https://example.com/a")
    path = Path(captured.item["text_path"])

    assert svc.remove(captured.item["id"]) is True
    assert not path.exists()
    conn = get_connection()
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM document_chunks").fetchone()[0] == 0
    assert await svc.search("attention residue") == []


def test_an_unknown_kind_names_the_ones_that_work(client):
    """A 400 that lists the accepted values is one the caller can act on."""
    response = client.post("/api/library", json={"title": "x", "kind": "zzz"})
    assert response.status_code == 400
    assert "article" in response.json()["detail"]


def test_the_library_page_loads_on_an_empty_database(client):
    response = client.get("/api/library")
    assert response.status_code == 200
    assert response.json() == {"items": [], "counts": {}, "query": ""}


async def test_the_reader_checks_every_redirect_hop(db, monkeypatch):
    """The guard itself, at the level it lives. `fetch_readable` walks Location
    by hand precisely so the second address is checked as hard as the first.

    Mutation check: hand httpx `follow_redirects=True` and check only the input.
    """
    from backend.web import reader

    checked: list[str] = []

    async def check(url, **kwargs):
        checked.append(url)
        if "169.254" in url:
            raise UnsafeURL("'169.254.169.254' resolves to a private or loopback address.")

    class Hop:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data/"}

    class Client:
        async def get(self, url, **kwargs):
            return Hop()

    monkeypatch.setattr(reader, "check_url_async", check)

    with pytest.raises(UnsafeURL):
        await reader._get_following_redirects(Client(), "https://example.com/go", timeout=1.0)
    assert checked == ["https://example.com/go", "http://169.254.169.254/latest/meta-data/"]
