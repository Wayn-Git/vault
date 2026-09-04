# Next session

Written 4 September 2026. Current as of this date.

> `docs/handover.md` is also titled "next session" and is **stale** — it says 507
> tests and 20 tools, both wrong by a wide margin. Trust this file for anything
> the two disagree on, and treat that one as history until somebody rewrites it.

## State

| | |
|---|---|
| Branch | `dev` |
| Last commit | `66c73c6` — Today, journal, library, brand kit |
| Working tree | **Uncommitted**: the whole Instagram feature |
| Tests | 736 passing, 1 skipped, 5 deselected |
| Tools | 25 builtin |
| Verified | `pytest`, `ruff check backend tests`, `npm run lint && npm run build` all clean |

---

## What shipped, in two passes

### Committed as `66c73c6`

- **Today** (`/today`, rail, `mod+8`) — calendar, task buckets, unread mail, logged
  items, connected tools, under a briefing regenerated each morning.
  `backend/journal/`.
- **Review agent** — the evening check-in is filed with the day's real numbers and
  **no prose**; the review is written from the user's own answers, and the notes
  are committed *before* the model call. Weekly rolls up the week's entries.
- **Library** (`/library`, `mod+9`) — paste a link, PSOK fetches it and writes the
  text to a real file under `~/.psok/library`, indexed by the same indexer that
  reads the vault. `backend/library/`.
- **Brand kit** — Settings → Brand, injected as `<brand>` into the system prompt.
- **Share endpoint** — `POST /api/share/capture`, token-gated, capture-only.

### Uncommitted (this session): Instagram capture

Send a reel to an Instagram account and it lands in the library — savetolist.com's
mechanic, on Meta's official API.

New: `backend/instagram/` (six files), `backend/media/`,
`backend/runtime/transcribe.py`, `backend/library/enrich.py`,
`docs/architecture/instagram.md`, four test files.

**Three routes, and they are not equal** — this is the thing to understand first:

| route | what Instagram actually gives you |
|---|---|
| mention (`@your.account` in a comment) | the real permalink **and** the full caption |
| DM'd reel | a title and an expiring CDN file. **No permalink, no caption.** |
| DM'd link | a permalink and nothing else |

A DM'd reel therefore has no text until its audio has one. So: download → ffmpeg →
`whisper-large-v3-turbo` on the existing Groq key. Then one model call produces a
summary, tags, and the concrete things the text names — a café, a grinder, a book.

**Nothing is invented.** `text_source == 'none'` makes `enrich_text` return before
a model client is even resolved, and `tests/test_enrichment.py` asserts the model
is *never called*. A reel with no words gets a sentence saying so where the summary
would be. This is the constraint the whole feature is shaped around; do not soften
it into a prompt instruction.

---

## What is blocked on you

Nothing in the code. Two setup jobs, both outside the repo:

**1. The Meta app.** No Facebook Page needed, and **no App Review or Business
Verification** — a Development-mode app works for its own admin/testers, which is
this single-user case. What silently does nothing when missed:

- the receiving account must be **Professional** (Business or Creator)
- the personal account doing the DMing must be added as a **tester** *and the
  invite accepted* in Instagram → Settings → Apps and websites → Tester invites
- scopes: `instagram_business_basic`, `_manage_messages`, `_manage_comments`

Then:

```bash
psok instagram credentials --app-secret … --verify-token … --access-token … --owner-id …
psok instagram enable
psok instagram senders --allow <your IGSID>
```

The allowlist starts **empty and nothing is ingested** — anyone can message a
public professional account. An unknown sender's delivery is recorded as
`ignored` with the id, and the Library panel offers "allow them?", because an
IGSID is an opaque number nobody can look up.

**2. Cloudflare Tunnel + Access.** Documented in `docs/deployment.md`, not built —
it needs a domain and a Cloudflare account. The rule that matters: only
`/api/share/capture` and `/api/instagram/webhook` may ever bypass Access, as
**exact paths**. A prefix bypass publishes a shell-executing API to the internet.

---

## Trying it without Meta

```bash
psok instagram send-sample --route dm-reel      # a correctly signed delivery
psok instagram queue
```

`send-sample` shares fixtures with the tests, so the manual loop and the suite
cannot drift. By hand, sign with `printf '%s' | openssl dgst -sha256 -hmac` — not
`echo`, whose trailing newline changes the HMAC and is why most hand-made
signature tests fail.

---

## Traps found and fixed — do not reintroduce

Each is guarded by a test with a "Mutation check:" line naming the way back in.

- **Meta sends `entry.time` in seconds and `messaging[].timestamp` in
  milliseconds**, in one delivery, with nothing saying so. Comparing the second
  against a seconds clock made every DM look decades old and the freshness window
  silently dropped it — a feature that appears to do nothing. `webhook._seconds`.
- **The signature must be verified over the raw request bytes.** A Pydantic model
  is deliberately *not* a route parameter: FastAPI would consume and re-encode the
  body, and a re-serialised body is not what Meta signed.
- **A module-level `asyncio.Event` across event loops** hung the entire suite
  (120s+ → 1.5s once fixed). Waiters bind to the loop that created them; the
  runner's Event and Lock are now built in `start()`. The other three runners
  avoid this by only using `sleep`.
- **`replace_text` left items unindexed** — dropping chunks and rewriting identical
  bytes means the content hash matches and the indexer skips the file. It now
  marks the path stale first.
- **`LibraryStore._UPDATABLE` is an allowlist and `update()` drops unknown keys
  silently.** Any new column must be added there or it is simply never written,
  with no error anywhere.
- **`remove()` used to unlink only `text_path`**, which would have orphaned 30MB
  mp4s forever once media existed.
- **`store.remove_chunks` assumed `chunk_vectors` exists** whenever sqlite-vec
  loads. It does not, on a machine that has only ever keyword-indexed.
- **`chunks_fts` was created only as a side effect of a working embedder**, so the
  half of search meant to survive a missing embedder had no table to write into.

---

## Environment notes

- **A fresh `PSOK_HOME` regenerates `providers.yaml` with stale default model ids.**
  Groq's `llama-3.3-70b-versatile` and Cerebras' `llama-3.3-70b` both 404 now. Every
  scratch-home test of anything model-backed fails for this reason and not because
  the feature is broken. Set a working tier first:
  `set_tier("fast", "groq", "openai/gpt-oss-20b")`.
- **Ollama is not running**, so semantic search degrades to keyword everywhere.
  That path is exercised and correct; it just logs a warning on every search.
- **Groq serves `whisper-large-v3` and `whisper-large-v3-turbo`** on the configured
  key — verified live. That is what makes DM'd reels searchable at all.
- `ffmpeg`/`ffprobe` present at `/usr/bin`. Bubblewrap available, so the sandbox is real.
- The frontend smoke suite (`npm run smoke`) **bails in the connectors section**
  against a scratch home with no MCP servers configured. Not a regression — it
  needs a home that has connectors.
- No stray credentials: the share token and all three Instagram secrets are
  confirmed absent from the real keychain.

---

## Suggested next steps, roughly by payoff

1. **Commit this.** It is a coherent feature with its own tests and docs.
2. **Do the Meta setup** and send a real reel. Everything below the webhook has been
   exercised with signed samples; only the Graph calls (`mentioned_media`, the
   thumbnail fetch, `send_text`) have not met the real API.
3. **`docs/handover.md` is stale enough to mislead.** Either rewrite it from this
   file and `README.md`, or delete the parts that are now wrong.
4. **The calendar is local-only.** `calendar_events` is a table the agent writes;
   Google Calendar is MCP tools and is not mirrored into it, so Today's schedule is
   empty on a machine that has never used `create_calendar_event`. That is the
   single biggest gap in Today being useful.
5. **`calendar_events` uses a `T` separator while `tasks` uses a space**, both
   compared by SQLite as strings. Documented at both writers and respected by
   `backend/journal/signals.py`; a proper `_normalise_calendar_timestamps`
   migration is still owed.
6. **Long-audio chunking** for transcription is explicitly out of scope for v1 —
   anything over ~15 minutes is refused with a stated reason rather than truncated.
7. **The Instagram token lasts 60 days** and refreshes only while still valid. The
   runner handles it at 14 days remaining; once lapsed there is no automatic
   recovery, only a re-paste.

---

## Ground rules this codebase holds to

Worth reading before changing any of the above, because every one of them has a
test or a comment defending it:

- **Nothing is invented.** Where a figure could not be measured or text does not
  exist, the interface says so and why — never a zero it did not check, never
  prose nobody could have written.
- **Interpretation is the model's job; computation is not.** Signals are gathered
  by SQL; the model only writes the sentences around them.
- **A capture that goes wrong still logs the item.** Every slow step is wrapped so
  a failure writes a sentence into `capture_note` and carries on.
- **The filesystem is the source of truth for text** (ADR-0004). The index points
  at files; `_store_text` is the single owner of that invariant.
- **Permission is a floor the model can raise but never lower.**
- **There is no authentication and there is not meant to be.** Exactly two paths
  are built to be reached from outside, each carrying its own credential.
