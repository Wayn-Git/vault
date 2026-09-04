# The library

Everything read, watched or listened to, logged as it is consumed, and findable
afterwards by meaning as well as by keyword.

`backend/library/` — `store.py` for the rows and the files, `service.py` for the
decisions. `backend/tools/builtin/library.py` and the `/api/library` routes are
thin callers, the same arrangement `backend/tasks/service.py` established.

## The text is a real file

`~/.psok/library/{id:06d}-{slug}.md`, indexed by the ordinary `Indexer` with
`source="library"`.

This is not a detail. PSOK stores an *index* that points at the filesystem and
treats the file as the source of truth (ADR-0004), and a synthetic
`psok://library/42` path would leave `mtime` and `size_bytes` NULL and break
that invariant to save one write. What the file buys instead:

* a real path, hash, size and mtime, so incremental re-indexing works unchanged
* **no second search stack** — chunking, FTS5, sqlite-vec, RRF and
  `SearchService` all apply, and `search_documents` finds a saved article in
  chat without knowing the library exists
* `documents.path` UNIQUE collisions are structurally impossible: the row id is
  allocated before the filename is built
* `Indexer._prune_missing` never touches these rows (it only scans
  `WHERE path LIKE '{root}%'` for a vault root), and would be *correct* if
  someone did index `~/.psok`
* the user can open the text

`SearchHit` carries `source` and `title`, and `label` prefers the title only for
non-vault sources — `documents.title` is `path.stem` for vault files, so
preferring it unconditionally would rename every existing hit from `notes.md` to
`notes`. It also drops a heading path identical to the title, because a captured
page is written with its title as the top heading and "Deep Work > Deep Work"
says nothing twice.

## A partial capture is still a capture

A paywall, a dead link, a video with no transcript, an embedder that is not
running — each loses part of what the item could have been, and none of them may
lose the fact that it was read. Every partial outcome writes `capture_note`
saying which one happened, and the interface shows it. An item with no text and
no explanation is indistinguishable from a bug.

`document_id IS NULL` is therefore a normal state, not an error.

Two consequences worth stating:

* `Indexer.index_file(..., require_embeddings=False)` indexes keyword-only when
  the embedder is unreachable. The vault path keeps `require_embeddings=True`:
  a broken embedder affects every file there and should fail once, loudly.
* `POST /api/library/{id}/reindex` calls `embeddings.forget_unreachable()`
  first. `_UNREACHABLE` is cached for the life of the process, so before this
  there was no way to start Ollama and get semantic search without restarting
  PSOK.

**No transcript scraping.** YouTube's oEmbed endpoint gives a title and a
channel with no API key; it does not give a transcript, and one PSOK invented
would be worse than none.

## Capture, and the SSRF fix that came with it

`backend/web/reader.py` is shared by `fetch_readable` and the `fetch_url` tool,
so the two cannot disagree about what a page says or which addresses are
refused. It follows redirects **by hand**, running `check_url_async` on every
hop.

That fixed a real hole: `fetch_url` used to validate the URL it was handed and
then pass `follow_redirects=True`, so a public address answering
`302 Location: http://169.254.169.254/` was fetched and its body handed to the
model. `tests/test_library.py` has the guard.

Text is capped at `MAX_TEXT_CHARS` (120,000). A 2 MB page is roughly 1,250
chunks and 40 embedding batches — minutes inside one POST, which is
indistinguishable from a hang.

## Saying what a thing is about

`backend/library/enrich.py` turns an item's text into a summary, three to eight
tags, and the concrete things it names -- a place, a product, a book, a recipe.
That list is the point: it is what makes a library answer "where was that
restaurant" rather than "here are forty links".

**It runs on text that exists, or it does not run.** `text_source` records where
an item's words came from -- `caption`, `transcript`, `page`, `notes`, or `none`
-- and `none` is a hard structural refusal: `enrich_text` returns before a model
client is resolved, and a test asserts the model is never called. Summarising a
reel that arrived with a title and no words would be inventing from a filename,
and the invention would be indistinguishable from the real thing on the page.

The result is stored **twice**, and neither place alone would do. The columns are
what the interface renders without parsing markdown. The item's own file gets it
too, and is re-indexed -- which is what puts the summary and the tags into search,
so "that video about coffee grind" finds a reel whose transcript never says the
phrase.

The file keeps the two kinds of words apart on purpose:

```markdown
# Pour-over ratios that actually matter

A short reel arguing grind size dominates brew ratio below 1:16...

Tags: coffee, pour-over, grind-size

## Mentioned
- product — Comandante C40: the grinder used
- place — Small Street Espresso: in Bristol

## Transcript
so the thing nobody tells you about pour over is ...

---
_Summary, tags and the list above were written by groq:... from the transcript.
The transcript is what was said._
```

The `## Transcript` heading is also what lets the source text be read back out on
a re-enrich -- without it, enriching twice would summarise the previous summary.

## Media

A captured video is downloaded only to be transcribed, and discarded afterwards
unless `instagram.keep_video` is on: twenty reels a day at fifteen megabytes is
nine gigabytes a year, and the words are the part worth keeping. Thumbnails
(~50 KB) stay. All of it lives under `~/.psok/library/media/` rather than beside
the markdown, which is a directory a person browses.

`LibraryService.remove` unlinks all three files. Without that, deleting an item
would leave an orphaned mp4 nothing would ever clean up.

## Getting a link in from elsewhere

Two mechanisms, and they are not the same thing.

**The bookmarklet** opens `/library?url=…` in a new tab. It is a navigation, so
no cross-origin request happens, nothing has to be switched on, and the CORS
allowlist stays as narrow as it is.

**The share token** is for a phone posting to a deployed instance:

```
POST /api/share/capture     Authorization: Bearer <token>     {"url": "..."}
```

It can log a URL and nothing else — it cannot read, list, delete or reach a
tool. It does not exist until `psok share-token --new` puts one in the OS
keychain; without one the route answers 404, because an endpoint that answers
401 is an endpoint worth guessing at. Comparison is constant time, and repeated
failures close the window for five minutes — including for the correct token,
which is deliberate: letting it through would be an oracle.

**A token does not make a public deployment safe.** Every other `/api` route is
unauthenticated by design (ADR-0001). See [deployment.md](../deployment.md).
