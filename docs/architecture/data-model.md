# Data Architecture

## The question this document answers

Where does each kind of information live? The brief was explicit that not everything belongs in one storage system, and Khoj is a live example of the opposite choice — one PostgreSQL instance with pgvector holding user data, transcripts, document text, and embeddings alike.

PSOK rejects both extremes.

**Khoj's single-store answer is wrong for PSOK's deployment shape.** PostgreSQL is a client-server database that expects to be administered: a service to run, a port to bind, a user and role to configure, a backup regime to maintain. Khoj is a hostable product with an operations story; PSOK is software one person runs on their own laptop. Requiring a database server before the first message is a real cost with no matching benefit.

**The opposite extreme — a relational database, plus a vector database, plus an object store, plus a cache — is also wrong.** Every additional engine is another process to run, another failure mode, another backup, and another consistency boundary. For a single user's personal data, that is infrastructure PSOK does not need and would have to operate forever.

The resolution: **one embedded engine, cleanly separated by domain, plus exactly two other mechanisms chosen because the embedded engine is actively wrong for that specific data type.**

## The three mechanisms

### 1. SQLite (with `sqlite-vec` and FTS5)

Everything relational, everything searchable, everything transactional. One file, WAL mode, no server, no port, no daemon. Backup is copying a file. `sqlite-vec` adds vector similarity search as an extension in the same database; FTS5 adds a real inverted index for keyword search.

The scale argument holds comfortably. A personal knowledge base of tens of thousands of documents produces low hundreds of thousands of chunks. `sqlite-vec` handles that range fine. The escape hatch, if a user ever exceeds roughly one to five million vectors, is swapping the vector tables for an embedded engine such as LanceDB — a change confined to the retrieval repository because nothing above it issues vector SQL directly. Recorded in [ADR-0002](decisions/0002-primary-database-engine.md) and [ADR-0003](decisions/0003-vector-storage.md).

### 2. The local filesystem

The user's actual documents. Not a copy, not an extraction — the files themselves, where the user put them.

This is a deliberate divergence from Khoj, which reads uploads into memory, extracts text, and discards the original bytes. That choice is privacy-friendly but forfeits three things PSOK needs: the ability to re-parse a document when the extractor improves, the ability to open the original from within PSOK, and the ability to keep binary content out of the database file. PSOK stores an *index* pointing at the filesystem — path, content hash, size, modification time — and treats the file as the source of truth.

### 3. The OS keychain

Every secret, without exception. macOS Keychain, Linux Secret Service via libsecret, Windows Credential Manager — reached through Python's `keyring` library.

Secrets in a database file are a real risk even when encrypted at rest, because the decryption key has to live somewhere the application can reach, which usually means next to the database. The keychain moves that problem to code that already solved it, with OS-level access control and, on desktop platforms, user-visible audit. The database holds only a *reference* — a keychain entry name — never a value. Recorded in [ADR-0012](decisions/0012-credential-storage.md).

## Placement, by data type

| Data type | Store | Why not elsewhere |
|---|---|---|
| App settings, confirmation preferences | SQLite | Small, relational, transactional; a config file cannot express "don't ask again for this operation subtype" cleanly |
| Tasks | SQLite | Needs relational queries — overdue, due today, blocked by another task. Wrong fit for a document blob or a vector index |
| Calendar events | SQLite | Same, plus sync identity (external id, etag) requiring row-level update semantics |
| Conversations and messages | SQLite, **normalized per message** | See below — this is a deliberate correction of Khoj |
| Document originals | **Filesystem** | Binary content bloats a database file and forfeits re-derivability |
| Document index | SQLite | Path, hash, size, mtime — relational metadata about filesystem objects |
| Chunks and embeddings | SQLite + `sqlite-vec` | Embeddings are tightly coupled to chunk metadata; separating them physically would mean a join across engines on the hottest path |
| Full-text search index | SQLite FTS5 | Same reason; and a real inverted index is what Khoj lacks |
| Execution audit log | SQLite, separate table | Kept out of `messages` because retention and pruning policy differ |

## Schema sketch

Illustrative, not final. Column lists show intent; types and indexes are settled during Phase 1.

### Conversations — normalized, not blobbed

```
conversations
  id, title, provider, model, created_at, updated_at,

messages
  id, conversation_id → conversations,
  role            (user | assistant | tool | system)
  content         TEXT
  tool_calls      JSON     -- assistant turns that requested tools
  tool_call_id    TEXT     -- tool results, linking back
  token_count     INT      -- cached, for budgeting without re-tokenizing
  created_at
  INDEX (conversation_id, created_at)
```

**Why this differs from Khoj.** Khoj stores an entire transcript as one JSON field, rewritten on every turn. That forfeits everything relational storage exists for: history is not queryable, truncation requires deserializing the whole blob, per-message indexing is impossible, and write cost grows with conversation length.

Normalized rows make budgeted truncation a `LIMIT`ed query, make "which conversations mention this file" answerable, and make appending a turn an insert. Tool calls and results stay as JSON *columns* because their shape is provider-shaped and genuinely variable — but they hang off a real row with a real foreign key. Recorded in [ADR-0017](decisions/0017-conversation-message-persistence-model.md).

### Documents, chunks, embeddings

```
documents
  id, path (UNIQUE), content_hash, file_type, size_bytes,
  mtime, indexed_at, title, source

document_chunks
  id, document_id → documents,
  chunk_index, heading_path, content TEXT,
  content_hash              -- per-chunk, for incremental re-indexing
  token_count, created_at
  INDEX (document_id), INDEX (content_hash)

chunk_embeddings          -- sqlite-vec virtual table
  chunk_id → document_chunks, embedding FLOAT[N], model_id

chunks_fts                -- FTS5 virtual table
  content, content_rowid = document_chunks.id
```

Content hashing at the chunk level is Khoj's incremental-indexing pattern and PSOK adopts it directly: hash each chunk, diff against stored hashes for that document, embed only what changed, delete what disappeared. Re-scanning an unchanged vault costs a hash comparison.

The separate `chunks_fts` table is the concrete upgrade over Khoj's ILIKE filtering. See [retrieval](#retrieval-notes) below.

### Tasks and calendar

```
tasks
  id, title, notes,
  due_at          TIMESTAMP   -- the deadline
  scheduled_at    TIMESTAMP   -- when work happens (distinct!)
  duration_estimate_minutes, status (todo|in_progress|done|cancelled),
  priority, source (user|agent),
  calendar_event_id → calendar_events,
  created_at, updated_at

calendar_events
  id, title, starts_at, ends_at, all_day, location,
  external_id, external_calendar_id, etag, last_synced_at,
  source (local | google), busy
  INDEX (starts_at, ends_at), UNIQUE (external_calendar_id, external_id)
```

`due_at` and `scheduled_at` being separate columns is the load-bearing detail for scheduling. "Due tomorrow" and "I will work on it at 2pm today" are different facts, and collapsing them makes conflict detection impossible. See [scheduling.md](scheduling.md).

### Audit log

```
execution_logs
  id, conversation_id, message_id,
  tool_name, tool_source          -- builtin | mcp
  arguments             TEXT      -- redacted JSON
  result_summary        TEXT      -- redacted, truncated
  error                 TEXT
  risk_level            TEXT      -- the level the gate resolved to, not the static floor
  confirmation_decision TEXT      -- auto | approved | denied | skipped_by_pref | denied_by_pref
  duration_ms           INT
  created_at
  INDEX (conversation_id, created_at), INDEX (tool_name, created_at)
```

`risk_level` records what the gate *decided*, so an escalation by self-report or
by the sensitive-path check is visible after the fact; `confirmation_decision`
records how that level was satisfied. Together they answer "why was this allowed
to run," which the tool name alone cannot.

**Redaction is mandatory on the audit path.** Arguments and results pass through a redactor before persistence, matching known credential-shaped fields and patterns. A log that captures tokens is a credential store with worse security properties.

## Retrieval notes

One decision shapes the schema above:

**Hybrid search means genuinely hybrid.** Vector similarity via `sqlite-vec` and BM25-style keyword ranking via FTS5, fused by reciprocal rank fusion, with metadata filters (path glob, date range, document type) applied as ordinary SQL predicates. Khoj calls vector-search-plus-ILIKE "hybrid," which oversells it — ILIKE is a substring scan with no ranking and no term statistics. Exact-term recall (a function name, an error code, an unusual proper noun) is precisely where dense vectors are weakest, so the inverted index is not a refinement, it is the other half.


## Consistency and concurrency

Concurrent writers exist despite the single user: the agent loop writes during a turn, and background sync workers write on their own schedule.

- **WAL mode** so readers see a consistent snapshot while a writer holds the write lock. A `find_free_slot` query during a calendar sync returns coherent data.
- **Small transactions in sync workers.** Per-item or small-batch commits, never one transaction wrapping an entire sync, so the write lock is never held long enough to block a conversation turn.
- **`busy_timeout` set** so brief contention retries instead of erroring.
- **Idempotent sync upserts** keyed on `(external_calendar_id, external_id)`, so a retried or overlapping sync converges rather than duplicating.

This resolves a genuine tension: the agent loop runs tools sequentially precisely to avoid races, and background workers reintroduce concurrency from outside the loop. WAL plus short transactions plus idempotent upserts is the answer.

## Filesystem and index consistency

If the filesystem is the source of truth for documents, the index can drift — and PSOK itself is one of the writers, since `write_file` and `edit_file` can modify an indexed file mid-conversation.

Three triggers keep them aligned: a **filesystem watcher** on the vault for external edits, an **explicit re-scan** on demand and at startup, and **direct invalidation** from PSOK's own file-mutating tools, which mark the affected document stale immediately rather than waiting for the watcher. Because re-indexing is content-hash incremental, all three are cheap.

## Data location summary

```
~/.psok/
  psok.db                 SQLite: everything relational + vectors + FTS
  psok.db-wal
  config/
    providers.yaml        model providers (keychain refs, no secrets)
    mcp.yaml              MCP server definitions
    sandbox.yaml          filesystem and network policy
  skills/                 user + seeded builtin skills
  logs/
  cache/

<user's vault>/           documents — the user's own directory, PSOK does not own it

OS keychain               every secret
```

## What is deliberately absent

No message broker, no Redis, no external vector database, no object storage, no separate search service, no container requirement. Each omission is a decision with a recorded rationale and, where relevant, a named migration path. The point is not minimalism for its own sake — it is that a single person must be able to run, back up, understand, and debug this system, and every added engine subtracts from that.
