# Khoj: Database, Storage, Retrieval, Memory

Repository: `/home/wayne/Documents/GitHub/khoj` — Python monolith, source under `src/khoj/`, Django ORM with a FastAPI request layer, PostgreSQL with pgvector.

## 1. What was investigated

How a personal-knowledge system stores and retrieves the user's own information: what database and schema, what lives in relational storage versus elsewhere, how documents are ingested and chunked, how embeddings are produced and searched, how conversational and long-term memory are represented, and the complete pipeline from an incoming document to context in a model prompt.

Deliberately not investigated: the web and plugin clients, subscription and rate-limiting logic, image generation, speech, and authentication beyond how it shapes the data model.

## 2. Relevant architecture

### Database

PostgreSQL only. `src/khoj/app/settings.py` hardcodes the Django Postgres backend with no SQLite fallback, and `docker-compose.yml` pins `pgvector/pgvector:pg15` — Postgres with the pgvector extension baked into the image and enabled by an early migration. There is no separate vector database, no document store, no object storage for text, and no cache layer beyond a small in-process query cache.

The schema is large: roughly forty model classes in one file, with about a hundred sequential migrations including several merge migrations from parallel branches — the signature of long organic evolution rather than up-front design.

The entities that matter for PSOK:

- **`Entry`** — the retrieval unit. Carries a pgvector `VectorField` for embeddings, the raw and compiled chunk text, a heading, file path/name/type/source, a `hashed_value` (content hash used for deduplication and incremental indexing), a `corpus_id` grouping all chunks derived from one source document, and a foreign key to `FileObject`. A database constraint ensures an entry belongs to either a user or an agent, never both.
- **`FileObject`** — the full extracted text of one ingested file, one row per file. Many `Entry` chunks point back to one `FileObject`.
- **`EntryDates`** — one row per date extracted from an entry, indexed, powering date-range filtering.
- **`Conversation`** — the entire chat transcript stored as a single JSON field, plus agent reference and file filters. A property validates that JSON blob into typed Pydantic message objects on read.
- **`UserMemory`** — long-term memory: a fact in raw text plus its embedding, with a reference to the embedding model used.
- **`SearchModelConfig`** — which bi-encoder and cross-encoder to use, where inference runs (local, HuggingFace endpoint, or OpenAI), and a confidence threshold.
- **`Agent`** — persona text, input tools and output modes as array fields, default chat model, privacy level.
- Provider configuration rows (`ChatModel`, `AiModelApi`), external-source connectors (`GithubConfig`, `NotionConfig`), and a generic key-value `DataStore`.

### Data access

All ORM access is funnelled through one adapters module (`src/khoj/database/adapters/__init__.py`, roughly 2,400 lines) organised into per-domain classes: `EntryAdapters`, `ConversationAdapters`, `FileObjectAdapters`, `UserMemoryAdapters`, `AgentAdapters`, and others. Routers never touch models directly — they call adapter methods. Sync and async variants exist side by side, with `asgiref.sync_to_async` bridging Django's synchronous ORM into FastAPI's async request path. A decorator guards adapter calls that require a valid user.

This is a repository/service layer over an ORM, and it is the right boundary. The only criticism is that it all lives in one very large file.

### Storage

**Original document bytes are never retained.** Uploads are read fully into memory, passed through format-specific text extractors (org-mode, markdown, plaintext, PDF, DOCX, images, Notion, GitHub), and only the extracted text is persisted. The original PDF or DOCX is discarded once parsed. There is no media root, no local document directory, no object store for documents.

Text is stored in two tiers, both in Postgres: `FileObject.raw_text` holds the whole file's text, and `Entry.raw`/`Entry.compiled` hold the embedded chunks.

Object storage exists but only for images: AI-generated images and user-attached chat images go to S3 when AWS credentials are configured, and the path is a no-op in self-hosted mode. So binary image assets leave the database; document text never does.

File metadata lives as plain columns on `Entry` rather than in a dedicated metadata table. External sources (GitHub, Notion) are re-fetched from the API on each sync using credentials stored in the database, rather than mirrored to disk.

A vestigial on-disk embeddings cache using `torch.save`/`torch.load` still exists in `search_type/text_search.py`, apparently predating the pgvector-backed design. The live server path does not use it.

### Retrieval

- **Chunking** (`src/khoj/processor/content/text_to_entries.py`) uses LangChain's recursive character splitter with a 256-token default chunk size, no overlap, a whitespace tokenizer, heading prefixes prepended to non-first chunks, and a stable `corpus_id` shared across all chunks from one logical source so results trace back to origin.
- **Embeddings** (`src/khoj/processor/embeddings.py`) wrap sentence-transformers for local inference (default `thenlper/gte-small`), or delegate to a HuggingFace inference endpoint or the OpenAI embeddings API, chosen by `SearchModelConfig`. Document and query encoding are asymmetric — separate encode paths — and vectors are normalized.
- **Vector search** is pgvector cosine distance in the same relational database: annotate with `CosineDistance`, order by distance, filter by a maximum distance.
- **"Hybrid" search is filtered vector search, not true hybrid.** Keyword filters (`+"word"` / `-"word"`) become `ILIKE` predicates, file filters become path regex, date filters join against `EntryDates`. These are ANDed with the vector ordering. There is no inverted index — no Postgres `tsvector`, no BM25, no Elasticsearch. Pure-keyword recall is correspondingly weaker than in systems with a real keyword index.
- **Reranking** uses a cross-encoder (default `mixedbread-ai/mxbai-rerank-xsmall-v1`) via sentence-transformers or a remote endpoint, invoked only when explicitly requested or when an inference server is configured, and only when there is more than one hit. Cross-encoder score takes precedence, falling back to bi-encoder distance.

### Memory

Two clearly separated tiers:

**Session memory** is the conversation transcript, appended into `Conversation.conversation_log` as a single denormalized JSON blob on every turn. There is no message table. On read it comes back wholesale and is then truncated to fit the token budget.

**Long-term memory** is the `UserMemory` table, and it is genuinely LLM-curated. After each turn, a memory-update routine (skipped entirely if the user has disabled memory) calls the model with a dedicated fact-extraction prompt — presented to the model as a memory-manager persona — passing the existing facts plus the latest exchange, and receives back a structured diff of facts to create and fact ids to delete, validated against a Pydantic schema. New facts are embedded and stored.

Recall happens two ways, both at the top of the chat pipeline: a recency window pulls memories updated within the last N days, and semantic search pulls memories near the current query by cosine distance above a confidence threshold. The two lists are merged and deduplicated by id, then injected as a dedicated block in the prompt and also used to inform tool selection and search-query inference.

## 3. Important implementation details

- **Content-hash incremental indexing.** Each chunk is MD5-hashed and diffed against the existing hashes for that file. Only genuinely new or changed chunks are embedded; stale hashes are deleted. Re-syncing an unchanged vault costs nothing beyond the hash comparison. For a personal knowledge base that re-syncs the same directory constantly, this is the difference between a usable and an unusable system.
- **Explicit token-budget management.** The maximum prompt size is looked up per model; the number of history turns kept scales from it (roughly the budget divided by 750); a truncation routine drops the oldest messages until the assembly fits. Context assembly is not best-effort — it is arithmetic.
- **Search queries are themselves generated by the model.** Before retrieval, an `extract_questions` call turns the user's message into one or more search queries. Retrieval runs per query and results are collated and deduplicated.
- **Prompt assembly is one function** (`generate_chatml_messages_with_context`) that composes system prompt, truncated history with each historical turn's own retrieved context re-embedded, newly retrieved document context, the memories block, and the current message.
- **Bulk operations everywhere on the write path** — chunk rows and date rows are bulk-created, not inserted one at a time.

### Data flow, end to end

1. Files arrive by upload from a client, or are pulled server-side from GitHub or Notion using stored credentials.
2. Content type is sniffed and a format-specific parser converts bytes to entry objects.
3. A dispatcher routes per-type file sets into the shared indexing pipeline.
4. Chunking splits entries by token count; each chunk is hashed and diffed against existing hashes for the file.
5. New and changed chunks are batch-embedded.
6. The full text is written to `FileObject`; chunk rows with embeddings are bulk-created; extracted dates are bulk-created; stale chunks are deleted.
7. At query time the chat pipeline generates search queries, runs vector search with filters, optionally reranks, and collates results.
8. Retrieved chunks plus recalled memories plus prior turns are assembled into a token-budgeted message list.
9. The assembled messages go to a provider-specific conversation module.
10. The turn is appended to the conversation log and the memory-extraction routine may persist new facts, closing the loop.

## 4. Why the architecture works

**One database is one thing to operate.** Everything — user data, transcripts, document chunks, embeddings, memories — lives in one Postgres instance. One backup, one connection pool, one migration history, one place to look. For a self-hostable product this is a serious feature, and it is achievable specifically because pgvector removes the usual reason to add a second store.

**The adapters layer keeps business logic out of the ORM and the ORM out of the routers.** Swapping how something is stored touches one class rather than every call site.

**Content hashing makes re-indexing cheap enough to run constantly**, which is what makes continuous sync from a live notes vault practical rather than a batch job the user avoids running.

**The two-tier memory split matches how memory is actually used.** Recent conversation needs to be verbatim and complete; older knowledge needs to be compressed, deduplicated, and semantically addressable. Storing both the same way would be wrong in one direction or the other. Having the model curate the long-term tier — including deletions, not just insertions — keeps it from growing into noise.

**Configurable embedding and reranking behind one config row** means local-versus-remote inference is a setting rather than a code path.

## 5. Trade-offs

**Conversations as one JSON blob.** The transcript is not queryable. There is no way to ask "which conversations mention this file" without deserializing every blob, no per-message indexing, no incremental append at the database level, and the whole blob is rewritten on every turn. It is simple and it is fast enough at small scale, but it forfeits everything relational storage was for.

**No real keyword index.** Calling ILIKE-filtered vector search "hybrid" oversells it. Exact-term recall — a function name, an error code, an unusual proper noun — is where pure vector search is weakest, and that is precisely the gap a BM25 or `tsvector` index fills.

**Discarding original document bytes** is privacy-friendly and matches Khoj's positioning, but it means a document can never be re-parsed with a better extractor, converted to another format, or opened by the user from within the system. Any improvement to the PDF parser only benefits documents the user re-uploads.

**Postgres requires operating Postgres.** For a hosted product this is nothing. For software a single person runs on their own laptop it is a container, a service, a port, and a backup story that a file would not need.

**File metadata as columns on the chunk row** denormalizes path, name, type, and source across every chunk of a file.

**One 2,400-line adapters file and roughly a hundred migrations** are maintenance costs of organic growth, not design choices worth reproducing.

## 6. What PSOK should adopt

- **Content-hash incremental indexing**, essentially unchanged. Hash each chunk, diff against stored hashes per file, embed only what changed, delete what disappeared.
- **Chunking with heading prefixes and a stable source identifier** tying every chunk back to its origin document.
- **A configurable embedding layer behind one interface**, local or remote, selected by configuration rather than by code path.
- **Explicit token-budget arithmetic** in context assembly: per-model budget, history scaling, oldest-first truncation. Not "keep the last ten messages."
- **Model-generated search queries** before retrieval, rather than embedding the raw user message.
- **A repository layer between the ORM and everything else** — but split per domain from the start rather than accumulating into one file.
- **Two-tier memory**: verbatim recent transcript plus an LLM-curated long-term fact store updated by a structured create/supersede diff, recalled by both recency and semantic similarity, merged and deduplicated, injected as a distinct prompt block, and switchable off by the user.
- **Optional reranking**, treated as a later refinement rather than a launch requirement.
- **Bulk write operations** on the indexing path.

## 7. What PSOK should avoid

- **Storing conversations as one JSON blob.** PSOK should use normalized per-message rows with tool calls and results as JSON columns on those rows. This makes history queryable, makes truncation incremental, and avoids rewriting the whole transcript every turn.
- **Calling filtered vector search "hybrid."** PSOK should pair vector search with a genuine inverted index — SQLite FTS5 — and fuse the two result sets, so exact-term queries actually work.
- **Discarding original documents.** PSOK should keep the user's files on the filesystem as the source of truth and store only an index pointing at them. This preserves re-derivability, avoids putting binary content in the database, and lets the user open their own files.
- **Requiring a client-server database for a single-user local application.** Postgres is the right answer for Khoj's hosted deployment and the wrong answer for PSOK's.
- **Letting the data-access layer accumulate into a single file** as the schema grows.
- **Leaving a superseded code path in place** (the on-disk torch embeddings cache) once the live path has moved elsewhere.

## 8. Relevant source files inspected

| Path | Responsibility |
|---|---|
| `src/khoj/app/settings.py` | Database configuration; Postgres-only backend |
| `docker-compose.yml` | pgvector image pinning |
| `src/khoj/database/models/__init__.py` | All ~40 model classes: `Entry`, `FileObject`, `EntryDates`, `Conversation`, `UserMemory`, `SearchModelConfig`, `Agent`, provider config |
| `src/khoj/database/migrations/0003_vector_extension.py` | pgvector extension enablement |
| `src/khoj/database/adapters/__init__.py` | The entire data-access layer: `EntryAdapters.search_with_embeddings`, `apply_filters`, `UserMemoryAdapters.save_memory`/`search_memories`, `ConversationAdapters.save_conversation` |
| `src/khoj/processor/content/text_to_entries.py` | Chunking, content hashing, incremental embedding update |
| `src/khoj/processor/content/{org_mode,markdown,pdf,docx,plaintext,notion,github,images}/*_to_entries.py` | Per-format text extraction |
| `src/khoj/processor/embeddings.py` | `EmbeddingsModel` and `CrossEncoderModel`: local, HuggingFace, and OpenAI inference paths |
| `src/khoj/search_type/text_search.py` | Query path, reranking, and the legacy on-disk embeddings cache |
| `src/khoj/search_filter/{word,file,date}_filter.py` | Keyword, path-glob, and date filter parsing |
| `src/khoj/routers/api_content.py` | Ingestion endpoint |
| `src/khoj/routers/api_chat.py` | Chat pipeline: query extraction, retrieval, memory recall, response generation |
| `src/khoj/routers/helpers.py` | File content extraction, search execution, memory update orchestration |
| `src/khoj/processor/conversation/utils.py` | Context assembly, token budgeting, truncation, conversation-log write-back |
| `src/khoj/processor/conversation/prompts.py` | Fact-extraction prompt and schema |
| `src/khoj/routers/storage.py` | S3 image upload, disabled when self-hosted |
