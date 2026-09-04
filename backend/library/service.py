"""The library: what you read, watched and listened to, and how to find it again.

One service, three thin callers -- the HTTP routes, the agent tools, and the
share endpoint -- following `backend/tasks/service.py`. The callers translate
arguments in and phrase results out; the decisions live here.

**The text is a real file.** PSOK stores an index that points at the filesystem
and treats the file as the source of truth (ADR-0004), so a captured article is
written to `~/.psok/library/{id}-{slug}.md` and indexed by the ordinary
`Indexer`. Nothing about search had to be taught the library exists: a saved
article is found by `search_documents` exactly as a vault note is, ranked by the
same hybrid index, and the user can open the file.

**A capture that goes wrong still logs the item.** A paywall, a 403, a video
with no transcript, an embedder that is not running -- each of those loses some
of what the item could have been, and none of them should lose the fact that you
read it. Every partial outcome writes `capture_note` saying which one happened,
because an item with no text and no explanation is indistinguishable from a bug.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from backend.db.connection import get_connection
from backend.library.store import KINDS, LibraryStore, text_path
from backend.mcp.ssrf import UnsafeURL, check_url_async
from backend.retrieval import store as index_store
from backend.retrieval.embeddings import forget_unreachable
from backend.retrieval.indexer import Indexer
from backend.retrieval.search import SearchService
from backend.web.reader import FetchError, fetch_readable, is_youtube, youtube_oembed

log = logging.getLogger(__name__)

#: Below this, the "text" is a cookie banner or a paywall stub rather than an
#: article, and indexing it would pollute the index with a page nobody read.
MIN_INDEXABLE_CHARS = 200

_KIND_BY_HOST = {
    "youtube.com": "video",
    "www.youtube.com": "video",
    "m.youtube.com": "video",
    "youtu.be": "video",
    "music.youtube.com": "podcast",
    "open.spotify.com": "podcast",
    "podcasts.apple.com": "podcast",
    "arxiv.org": "paper",
    "www.arxiv.org": "paper",
}


class LibraryError(ValueError):
    """Something the caller can fix, phrased for whoever asked."""


@dataclass
class Captured:
    item: dict
    already_logged: bool = False


def kind_for(url: str | None) -> str:
    if not url:
        return "note"
    host = (urlparse(url).hostname or "").lower()
    return _KIND_BY_HOST.get(host, "article")


def as_dict(row) -> dict:
    """One item, as the interface and the model both see it."""
    data = dict(row)
    data["indexed"] = data.get("document_id") is not None
    return data


class LibraryService:
    def __init__(self, store: LibraryStore | None = None, indexer=None, fetcher=None):
        # Injected so a test never reaches the network or an embedding server,
        # and so the share endpoint and the tool share one implementation.
        self.store = store or LibraryStore()
        self._indexer = indexer
        self._fetch = fetcher or fetch_readable

    @property
    def indexer(self) -> Indexer:
        if self._indexer is None:
            self._indexer = Indexer()
        return self._indexer

    # -- capture ---------------------------------------------------------

    async def capture_url(
        self,
        url: str,
        *,
        kind: str | None = None,
        consumed_on: str | None = None,
        notes: str | None = None,
        title: str | None = None,
    ) -> Captured:
        """Log a URL, fetching whatever text it will give up."""
        url = (url or "").strip()
        if not url:
            raise LibraryError("a url is needed")
        if "://" not in url:
            url = f"https://{url}"
        if kind and kind not in KINDS:
            raise LibraryError(f"unknown kind '{kind}'. One of: {', '.join(KINDS)}")

        try:
            await check_url_async(url)
        except UnsafeURL as exc:
            raise LibraryError(str(exc)) from exc

        existing = self.store.by_url(url)
        if existing is not None:
            # Re-pasting a link is how you land here, and a duplicate row plus a
            # second fetch is not what that meant.
            return Captured(as_dict(existing), already_logged=True)

        page = None
        capture_note = ""
        if is_youtube(url):
            # YouTube's watch page is a script bundle; oEmbed is the only thing
            # it will state plainly, and it does not carry a transcript.
            meta = await youtube_oembed(url)
            if meta:
                title = title or meta["title"]
                author = meta.get("author") or None
                site = meta.get("site")
            else:
                author = site = None
                capture_note = "YouTube did not answer for this video's title"
            capture_note = capture_note or "video: title and channel only, no transcript available"
            published_on = None
            text = ""
        else:
            try:
                page = await self._fetch(url)
            except UnsafeURL as exc:
                raise LibraryError(str(exc)) from exc
            except FetchError as exc:
                capture_note = str(exc)
            title = title or (page.title if page else None)
            author = page.author if page else None
            site = page.site if page else None
            published_on = page.published_on if page else None
            text = page.text if page else ""
            if page and page.note:
                capture_note = page.note

        item_id = self.store.create(
            kind=kind or kind_for(url),
            title=(title or url)[:400],
            url=url,
            author=author,
            site=site,
            published_on=published_on,
            consumed_on=consumed_on or date.today().isoformat(),
            notes=notes,
        )

        note = await self._store_text(item_id, title or url, text, capture_note)
        self.store.update(item_id, capture_note=note or None)
        return Captured(as_dict(self.store.get(item_id)))

    async def log_manual(
        self,
        *,
        title: str,
        kind: str = "note",
        text: str | None = None,
        url: str | None = None,
        author: str | None = None,
        notes: str | None = None,
        consumed_on: str | None = None,
        rating: int | None = None,
    ) -> Captured:
        """Log something with no URL to fetch -- a book, a talk, a conversation."""
        title = (title or "").strip()
        if not title:
            raise LibraryError("a title is needed")
        if kind not in KINDS:
            raise LibraryError(f"unknown kind '{kind}'. One of: {', '.join(KINDS)}")

        item_id = self.store.create(
            kind=kind,
            title=title[:400],
            url=(url or "").strip() or None,
            author=author,
            site=None,
            consumed_on=consumed_on or date.today().isoformat(),
            notes=notes,
            rating=_rating(rating),
        )
        # Notes are the text when there is no body: what you wrote about a book
        # is the only searchable thing about it.
        body = (text or "").strip() or (notes or "").strip()
        note = await self._store_text(item_id, title, body, "", fetched=False)
        self.store.update(item_id, capture_note=note or None)
        return Captured(as_dict(self.store.get(item_id)))

    async def _store_text(
        self, item_id: int, title: str, text: str, note: str, *, fetched: bool = True
    ) -> str:
        """Write the text to disk and index it. Returns the note to record.

        `fetched` says whether there was a page to read. A book logged with two
        lines of your own notes is complete; a *page* that returned two lines is
        a paywall, and only the second is worth a note.
        """
        text = (text or "").strip()
        if not text:
            return note or (
                "no text was captured, so this is findable by its title and notes only"
            )
        if fetched and len(text) < MIN_INDEXABLE_CHARS and not note:
            note = "the page gave up very little text"

        path = text_path(item_id, title)
        try:
            path.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
        except OSError as exc:
            log.warning("could not write library text for %s: %s", item_id, exc)
            return f"the text could not be saved: {exc}"

        report = await self.indexer.index_file(
            path, source="library", title=title, require_embeddings=False
        )
        document = get_connection().execute(
            "SELECT id FROM documents WHERE path = ?", (str(path.resolve()),)
        ).fetchone()
        self.store.update(
            item_id,
            document_id=document["id"] if document else None,
            text_path=str(path),
            word_count=len(text.split()),
        )
        if report == 0 and document is None:
            return note or "the text could not be indexed"
        return note

    # -- maintenance -----------------------------------------------------

    async def reindex(self, item_id: int) -> dict:
        """Index an item's text again, first forgetting a refused embedder.

        `_UNREACHABLE` is cached for the life of the process, so an item captured
        while Ollama was down stays keyword-only until something clears it. This
        is that something: starting Ollama and pressing re-index is enough, and
        restarting PSOK is not required.
        """
        row = self.store.get(item_id)
        if row is None:
            raise LibraryError(f"no library item {item_id}")
        if not row["text_path"]:
            raise LibraryError("there is no captured text for this item to index")
        path = Path(row["text_path"])
        if not path.exists():
            raise LibraryError(f"the captured text is missing from {path}")

        forget_unreachable()
        # Force a re-embed rather than trusting the content hash: the text has
        # not changed, the index is what was incomplete.
        self.indexer.mark_stale(path)
        if row["document_id"]:
            self._drop_chunks(row["document_id"])
        await self.indexer.index_file(
            path, source="library", title=row["title"], require_embeddings=True
        )
        document = get_connection().execute(
            "SELECT id FROM documents WHERE path = ?", (str(path.resolve()),)
        ).fetchone()
        self.store.update(
            item_id,
            document_id=document["id"] if document else None,
            capture_note=None,
        )
        return as_dict(self.store.get(item_id))

    def _drop_chunks(self, document_id: int) -> None:
        conn = get_connection()
        chunk_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM document_chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
        ]
        index_store.remove_chunks(conn, chunk_ids)
        conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
        conn.commit()

    def remove(self, item_id: int) -> bool:
        """Delete an item, its text, its chunks and its index entries."""
        row = self.store.get(item_id)
        if row is None:
            return False
        conn = get_connection()
        if row["document_id"]:
            self._drop_chunks(row["document_id"])
            conn.execute("DELETE FROM documents WHERE id = ?", (row["document_id"],))
            conn.commit()
        if row["text_path"]:
            Path(row["text_path"]).unlink(missing_ok=True)
        return self.store.delete(item_id)

    # -- reading ---------------------------------------------------------

    def recent(self, *, kind: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
        return [as_dict(row) for row in self.store.list(kind=kind, limit=limit, offset=offset)]

    async def search(self, query: str, *, limit: int = 20) -> list[dict]:
        """Find library items by meaning and by keyword, ranked together.

        Results are items, not chunks: a hit is joined back to what you read, so
        the answer is "this article, and the passage that matched" rather than a
        path under ~/.psok.
        """
        query = (query or "").strip()
        if not query:
            return []
        hits = await SearchService().search(query, limit=limit * 3, source="library")
        if not hits:
            return []

        conn = get_connection()
        placeholders = ",".join("?" * len(hits))
        rows = conn.execute(
            "SELECT c.id AS chunk_id, c.document_id FROM document_chunks c"
            f" WHERE c.id IN ({placeholders})",
            [hit.chunk_id for hit in hits],
        ).fetchall()
        document_for = {row["chunk_id"]: row["document_id"] for row in rows}
        items = self.store.by_document_ids(sorted({row["document_id"] for row in rows}))

        out: list[dict] = []
        seen: set[int] = set()
        for hit in hits:
            document_id = document_for.get(hit.chunk_id)
            item = items.get(document_id) if document_id else None
            if item is None or item["id"] in seen:
                continue
            seen.add(item["id"])
            out.append({**as_dict(item), "excerpt": _excerpt(hit.content), "score": hit.score})
            if len(out) >= limit:
                break
        return out

    def counts(self) -> dict[str, int]:
        return self.store.counts()


def _rating(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return min(5, max(1, number))


def _excerpt(content: str, *, limit: int = 320) -> str:
    text = " ".join(content.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def describe(item: dict) -> str:
    """One line about an item, for a model reading a tool result."""
    bits = [item["title"]]
    if item.get("author"):
        bits.append(f"by {item['author']}")
    bits.append(f"({item['kind']}, logged {item['consumed_on']})")
    if item.get("capture_note"):
        bits.append(f"-- {item['capture_note']}")
    return " ".join(bits)
