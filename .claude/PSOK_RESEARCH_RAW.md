# PSOK Raw Research Dump (Pipali / Khoj / LibreChat + Synthesized Architecture Design)

Captured verbatim from the research/design subagent runs during the PSOK architecture-planning session, before doc files were written. Kept here for any future agent/session to pick up without re-running the research. Source repos:
- Pipali: /home/wayne/Documents/GitHub/pipali
- Khoj: /home/wayne/Documents/GitHub/khoj
- LibreChat: /home/wayne/Documents/GitHub/LibreChat

Stack decision made by user for the eventual implementation: **Python (backend) + React (frontend)**. The three research reports below predate that decision and cite the source repos' own stacks (Bun/TS for Pipali, Django/Python for Khoj, Node for LibreChat) — that's fine, they're about *architecture patterns*, not PSOK's stack. The synthesized design section at the end originally assumed TS/Bun for PSOK itself; treat those specific tech mentions there as superseded by Python+React, everything else (layer diagram, data placement, permission model, ADR list, phase ordering) stands.

---

## 1. Pipali Research — Computer/Shell/Skills/Tools

Repo: `/home/wayne/Documents/GitHub/pipali` — Bun + Hono backend, React 19 frontend, Tauri desktop wrapper. Core docs: `README.md`, `CONTRIBUTING.md` (has an explicit architecture section with ASCII diagrams — read this first, it's largely accurate against the code).

### 1.1 Desktop/Computer Interaction

There is **no generic OS/GUI automation abstraction** (no mouse/keyboard/screenshot control of the desktop, no "computer use" tool). The agent interacts with the machine through two narrower surfaces:

- **Filesystem tools** (actors): `view_file`/`read_file`, `list_files`, `grep_files`, `edit_file`, `write_file` — `src/server/processor/actor/{read_file,list_files,grep_files,edit_file,write_file}.ts`. These are plain Node/Bun `fs` calls, not OS-abstracted; platform differences (path separators, home dir) are handled ad hoc via `path`/`os`.
- **Shell execution** (see 1.2) for everything else (process control, package installs, running scripts).
- **Browser/GUI-style interaction** is delegated to a built-in MCP server, `chrome-browser` (wraps `chrome-devtools-mcp`), auto-installed on first run in `src/server/init.ts:120-159`. Its enabled tools include `click`, `drag`, `fill`, `fill_form`, `hover`, `press_key`, `take_screenshot`, `take_snapshot`, `navigate_page`, `upload_file`, etc. — this is effectively the "desktop interaction" layer, but scoped to a Chrome instance, not the whole OS.

**Permission model:**
- A single **confirmation service** (`src/server/processor/confirmation/confirmation.service.ts`, `confirmation.types.ts`) gates all "dangerous" operations (`edit_file`, `write_file`, `delete_file`, `execute_command`, `mcp_tool_call`, `read_sensitive_file`, `grep_sensitive_path`, `fetch_internal_url`). It's transport-agnostic — a callback (`ConfirmationCallback`) is supplied by the WebSocket layer (`src/server/routes/ws/confirmation-manager.ts`) which round-trips a request to the client UI and waits (with a generous 24h timeout for unattended/scheduled runs, `CONFIRMATION_TIMEOUT_MS` at `confirmation.service.ts:27`).
- Risk level (`low/medium/high`) is derived per-operation, and users can pick "Yes, don't ask again," which persists a skip-key (e.g. `execute_command:read-only`) in `ConfirmationPreferences` (per-user, DB-backed).
- **Sensitive path detection**: `src/server/security/path-validator.ts` — regex list for `.ssh`, `.aws`, `.gnupg`, `.npmrc`, `.env`, shell history, browser profile dirs, etc.; used to force confirmation on reads/greps of those paths even outside the sandbox.
- **Restriction of dangerous actions for MCP tools (which is how most "desktop/GUI" actions like browser clicks flow)**: each MCP tool call must self-report `operation_type: 'safe'|'unsafe'`, and the server has a `confirmationMode` (`always`/`unsafe_only`/`never`) — logic in `src/server/processor/mcp/manager.ts:296-318` (`shouldRequireConfirmation`) and `executeMcpTool` (`manager.ts:346-400`). Notably, **the model itself decides whether its own action is "safe" or "unsafe"** — a self-declared risk classification, same pattern as `shell_command`'s `operation_type`. Unspecified defaults to requiring confirmation.
- **Results returned to the agent** as plain strings (or, for images, multimodal content blocks) embedded in the tool-call response consumed by the director loop (`compiled` field on every actor result, see `ShellCommandResult`, `WriteFileResult`, etc. — all share `{query, file, uri, compiled}`).

Worth flagging: MCP server processes (including the browser-control server) are spawned as **regular child processes via `StdioClientTransport`** (`src/server/processor/mcp/client.ts:360`, `Bun.spawn` at lines 210/235) — they are **not** run inside the OS sandbox that shell commands get. The only gate on MCP/browser actions is the confirmation system, which relies on the model's own safe/unsafe self-report.

### 1.2 Bash/Shell

**Core file**: `src/server/processor/actor/shell_command.ts` — this is the single component that executes shell commands. Exposed to the LLM as the `shell_command` tool, schema defined inline in `src/server/processor/director/index.ts:346-395` (plus a companion `stop_process` tool at lines 396-409).

Key behaviors:
- **Platform dispatch**: bash (`/bin/bash -c`) on macOS/Linux, PowerShell on Windows (`shell_command.ts:228-241`). Tool description and args text differ per-platform (director/index.ts:348-350, 360-362).
- **Execution modes**: `sandbox` (default, OS-enforced, skips confirmation) vs `direct` (full access, requires user confirmation) — resolved at `shell_command.ts:170-188`.
- **stdout/stderr/exit code**: captured via `Bun.spawn` with piped stdout/stderr (`shell_command.ts:255-266`); exit code appended to output if non-zero (`313-316`); sandbox violations detected either via `SandboxManager.annotateStderrWithSandboxFailures` or pattern-matching `EPERM`/"Permission denied" (`280-324`), with a helpful note injected back to the model telling it to retry in `direct` mode.
- **Timeouts**: default 30s, max 60s in-process (`DEFAULT_TIMEOUT_MS`/`MAX_TIMEOUT_MS`, `shell_command.ts:92-95`), though the tool schema advertises up to 300000ms — clamped internally. Timeout errors are caught and returned as a normal tool message (`334-345`), not thrown to the caller.
- **Background execution**: `run_in_background: true` hands off to `src/server/events/background-processes.ts` — output is written to a log file (not piped), the agent gets a pid + log path back and reads it via `tail`/`grep` through subsequent `shell_command` calls; exit is reported asynchronously into the conversation via `deliverToParent` (parent-inbox). Concurrency capped at 10 (`MAX_CONCURRENT`), with SIGTERM→2s grace→SIGKILL on `stop_process`.
- **Failure handling**: all failure modes (bad cwd, empty command, timeout, spawn error) return structured error strings rather than throwing, so the agent loop always gets a tool result to reason over.

**Sandboxing** (`src/server/sandbox/`):
- `config.ts` — declarative `SandboxConfig` (enabled, allowedWritePaths, deniedWritePaths, deniedReadPaths, allowedDomains, allowLocalBinding) with sensible defaults (deny-read for `.ssh`/`.aws`/`.env`/etc., allow-write for `/tmp` and `~/.pipali`, allow-domains for npm/pypi/github/model APIs).
- `index.ts` — thin wrapper over `@anthropic-ai/sandbox-runtime`'s `SandboxManager`: macOS uses Seatbelt (`sandbox-exec`), Linux uses Bubblewrap (`bwrap`), **Windows is unsupported** and always falls back to confirmation-based direct execution. `wrapCommandWithSandbox()` shells out to `SandboxManager.wrapWithSandbox` to produce the sandboxed command string.
- `settings.ts` — per-user settings persisted in DB (`SandboxSettings` table), loaded/merged with defaults at startup (`initializeSandbox()`), reloadable at runtime.
- Sandbox env overrides redirect tool caches (uv, pip, npm, bun) into `/tmp/pipali` so they don't hit the deny-write list (`getSandboxEnvOverrides`, `index.ts:372-391`).

**Trusted vs untrusted commands**: There's no allow/deny command list — trust is expressed purely through `execution_mode` + the sandbox filesystem/network policy + user confirmation for anything outside the sandbox. The agent is expected to self-classify `operation_type` (`read-only`/`write-only`/`read-write`), which maps to risk level for confirmation purposes (`confirmation.service.ts:65-79`) — again a model self-report rather than static analysis of the command.

### 1.3 Skills

A **skill** is a directory containing a required `SKILL.md` (YAML frontmatter + markdown body) plus optional `scripts/`, `references/`, `assets/`, and an optional `scripts/package.json`. Follows the public agentskills.io spec. Type definition: `src/server/skills/types.ts`:
```ts
interface Skill { name: string; description: string; location: string; visible: boolean; }
```
- **Storage location**: `~/.pipali/skills/<skill-name>/` (`getSkillsDir()` in `src/server/skills/index.ts:104-106`, backed by `src/server/paths.ts`). Builtin skills ship in `src/server/skills/builtin/` (document-creator, introspect, skill-creator) and are copied into the user's skills dir on first run (`installBuiltinSkills`, handles both dev-mode filesystem copy and compiled-binary embedded-asset copy, `index.ts:116-244`), without overwriting user edits.
- **Discovery/loading**: `src/server/skills/loader.ts` — `scanSkillsDirectory()` walks `~/.pipali/skills/`, validates each subdir's `SKILL.md` (name must match dir name, name regex `^[a-z0-9](...)$` max 64 chars, description 1-1024 chars), returns `{skills, errors}`. `loadSkills()` in `index.ts:250-254` caches the result in module-level `cachedSkills`; `getLoadedSkills()` returns the cache.
- **Invocation**: there is **no dedicated `invoke_skill` tool call**. Loaded skills are formatted as XML (`formatSkillsForPrompt` in `src/server/skills/utils.ts`) and injected into the system prompt (`director/index.ts:189`, `buildSystemPrompt`) as name+description+**location path** only — this is progressive disclosure. The model is expected to call the ordinary `view_file` tool on the `location` path to read the full `SKILL.md` instructions when relevant, then can run any `scripts/*` via `shell_command`, or read `references/*` via `view_file`/`grep_files`. So skills are just markdown+scripts consumed through existing generic tools, not a separate execution mechanism.
- **Skill selection**: entirely up to the LLM's judgment based on the name/description summary in the system prompt — no programmatic router/matcher chooses skills.
- **CRUD API**: `createSkill`, `getSkill`, `updateSkill`, `deleteSkill`, `toggleSkillVisibility` in `src/server/skills/index.ts`, exposed at `src/server/routes/api.ts:744` (`getSkill(name)` for the skills UI/detail view). The `skill-creator` builtin skill (`src/server/skills/builtin/skill-creator/SKILL.md`) is itself the meta-guide the agent reads when asked to author a new skill.
- Skills with a `scripts/package.json` get npm deps installed automatically at install time via the bundled Bun runtime (`installSkillDependencies`, `index.ts:67-99`) — so skills can bring their own dependency trees (seen in `document-creator`'s docx/xlsx Python+TS scripts).

### 1.4 Tool Execution Flow (End to End)

1. **Client → server**: WebSocket `message` command → `MessageCommandHandler.execute` (`src/server/routes/ws/commands/message.ts`). Resolves/creates a `Conversation` row, creates a `session` with fresh `ConfirmationPreferences`, and either queues onto an active run or hands off to the run executor.
2. **Run executor**: `src/server/events/run-executor.ts` — builds a `ConfirmationContext` whose callback is `createConfirmationCallback` (`src/server/routes/ws/confirmation-manager.ts`), which publishes confirmation requests onto a `ConversationEventBus` (per-conversation pub/sub) and waits for a client response (or times out after 24h).
3. **Research runner**: `src/server/processor/research-runner.ts` (`runResearchWithConversation`) — loads/persists the ATIF conversation trajectory (`src/server/processor/conversation/atif/*`, JSON stored as JSONB in PGlite), then drives the director's `research()` async generator, persisting each step (system/user/agent + tool_calls + observations) back to the DB and forwarding iterations to WS callbacks for streaming UI updates.
4. **Director** (`src/server/processor/director/index.ts`):
   - `buildSystemPrompt()` assembles the system prompt including the skills XML block, user context, date/time/location/OS info.
   - `pickNextTool()` calls the LLM (`sendMessageToModel`) with the full tool list (`getAllTools()` = built-in actors + delegation tools + MCP tool definitions, with tool-search-based deferral for large MCP tool sets) and parses returned `function_call`s into `ATIFToolCall`s.
   - `executeTool()` dispatches by name: MCP tools (name contains `__`) go through `executeMcpTool`; built-ins go through a big `switch` calling the actor functions (`shellCommand`, `writeFile`, `editFile`, `readFile`, `grepFiles`, `listFiles`, `webSearch`, `readWebpage`, `generateImage`, `emailUser`, `askUser`, `delegateTask`, etc.), each actor receiving a `ToolExecutionContext` carrying `confirmation`, `conversationId`, `user`, `abortSignal`, etc.
   - `executeToolsInParallel()` runs all tool calls from one LLM turn concurrently via `Promise.allSettled`-style racing against the abort signal, so a pause/interrupt cleanly marks pending calls `[interrupted]`.
   - `research()` is the actual loop: call LLM → get tool calls → yield "tool call start" (so UI can show pending state) → execute tools → yield results → loop until the LLM responds with no tool calls (or iteration cap / retry-warning cap is hit).
5. **Individual tool → OS**: e.g. `shell_command` → sandbox wrap (or confirmation gate) → `Bun.spawn` → OS process → stdout/stderr/exit code captured → truncated (`truncateToolOutput`, 100k char cap, `director/index.ts:77-110`) → returned as the tool's `compiled` string.
6. **Result → agent → user**: tool results become an `agent` step's `observation` in the ATIF trajectory, fed back into the next LLM call as conversation history; the final assistant message (no tool calls) is persisted and streamed to the client over the same WebSocket/event-bus path.

### 1.5 Notable Design Patterns (Pipali)
- **Self-reported risk classification** as the primary confirmation-gating signal, for both shell commands (`operation_type`) and MCP tools (`operation_type: safe/unsafe`) — convenient but relies on the model's honesty/accuracy rather than static/deterministic analysis.
- **Uniform `{query, file, uri, compiled}` result shape** across nearly all actors — keeps `director.ts`'s dispatch and truncation logic generic.
- **Progressive disclosure for both skills and MCP tools** — skills via name+description+location (read full doc on demand), many-MCP-tool sets via `search_tools`/deferred loading — both are solving the same "don't blow the context budget" problem with parallel mechanisms.
- **Confirmation system is fully transport-agnostic** (`ConfirmationCallback` type) and **operation-scoped preference persistence** (`skipConfirmationFor` keyed by `operation[:subtype]`) gives fairly fine-grained "don't ask again."
- **Sandbox vs. confirmation are complementary, not layered** — sandboxed commands skip confirmation entirely (trusting the OS enforcement); direct-mode commands get no sandboxing at all but require a human click. There's no "sandboxed AND confirmed" tier.
- **Windows has no sandbox** at all — every shell command there requires confirmation, a meaningfully different security posture per OS that's worth flagging for any cross-platform threat model.
- **MCP child processes (including the default browser-automation server) run outside the sandbox** — worth flagging as the main gap in an otherwise sandboxed-by-default design; browser-driven "desktop-like" actions (clicking, form-filling, navigating) are gated only by the model's own safe/unsafe self-classification plus optional user confirmation, not OS-level containment.

---

## 2. Khoj Research — Database/Storage/Retrieval/Memory

Repo root: `/home/wayne/Documents/GitHub/khoj` (Python/Django + FastAPI monolith, source under `src/khoj/`)

### 2.1 Database

**Engine:** PostgreSQL only (no SQLite fallback despite "self-hostable" framing) — `src/khoj/app/settings.py:178-186` hardcodes `"ENGINE": "django.db.backends.postgresql"`, reading `POSTGRES_DB/HOST/PORT/USER/PASSWORD` env vars. `docker-compose.yml:3` pins the image to `docker.io/pgvector/pgvector:pg15` — i.e., Postgres with the **pgvector** extension baked in, enabled via migration `src/khoj/database/migrations/0003_vector_extension.py` (`VectorExtension()`).

**ORM:** Standard Django ORM. App is `src/khoj/database/` (models in `database/models/__init__.py`, ~865 lines, 40+ model classes; ~100 sequential migrations in `database/migrations/`, showing long, organic schema evolution incl. several merge migrations from parallel branches).

**Major entities** (`database/models/__init__.py`):
- `KhojUser` (extends Django `AbstractUser`, adds `uuid`, phone/email verification) — L153; `GoogleUser`, `KhojApiUser` (API tokens), `Subscription`.
- `Conversation` (L658) — `user` FK, `conversation_log` (JSONField holding the full chat transcript), `agent` FK, `file_filters` (JSONField), UUID PK. Has a `messages` property that validates the JSON blob into typed `ChatMessageModel` (Pydantic) objects, and a `pop_message()` for interruption handling.
- `Agent` (L248) — persona/tools config: `personality` (text), `input_tools`/`output_modes` (Postgres `ArrayField`), `chat_model` FK, `privacy_level` (public/private/protected), auto-slug generation.
- `Entry` (L768) — the core knowledge-base row: `embeddings = VectorField(dimensions=None)` (pgvector), `raw`/`compiled` text, `heading`, `file_path`/`file_name`/`file_type`/`file_source`, `hashed_value` (content hash for dedup), `corpus_id` (groups chunks of the same source doc), FK to `FileObject`. Constrained so an Entry belongs to either a `user` or an `agent`, never both.
- `EntryDates` (L806) — one row per date mentioned/extracted in an entry, indexed, used for date-range filtering.
- `FileObject` (L760) — holds the **full raw text** of an ingested file (`raw_text = TextField()`), one row per file; `Entry` rows reference it via FK (many chunks → one FileObject).
- `UserMemory` (L855) — long-term memory store: `embeddings = VectorField(...)`, `raw` text, FK to `user`/`agent`, `search_model` FK.
- `SearchModelConfig` (L544) — configurable embedding/reranking model choice (bi-encoder + cross-encoder names, HF/OpenAI/local inference endpoint config, `bi_encoder_confidence_threshold`).
- `ChatModel`, `AiModelApi`, `TextToImageModelConfig`, `SpeechToTextModelOptions`, `VoiceModelOption` — LLM/provider configuration rows (OpenAI/Anthropic/Google types).
- `GithubConfig`/`GithubRepoConfig`, `NotionConfig`, `WebScraper` — external data source connectors.
- `ProcessLock`, `UserRequests`, `RateLimitRecord`, `DataStore` (generic KV JSONField store), `McpServer`.

**Data-access pattern:** A single large **adapters** module, `src/khoj/database/adapters/__init__.py` (2374 lines), wraps all Django ORM queries behind static/async methods grouped into classes per domain — `AgentAdapters`, `ConversationAdapters`, `FileObjectAdapters`, `EntryAdapters`, `AutomationAdapters`, `McpServerAdapters`, `UserMemoryAdapters`, etc. This is the repository/service-layer pattern sitting on top of Django's ORM — routers never touch models directly, they call adapter methods. Both sync (`get_x`) and async (`aget_x`) variants exist throughout (uses `asgiref.sync_to_async` to bridge Django's sync ORM into the async FastAPI request path). A `@require_valid_user` / `@arequire_valid_user` decorator (L106-140) guards adapter calls.

### 2.2 Storage

- **No blob/object storage for raw uploaded files on the server.** In `src/khoj/routers/api_content.py`, uploaded files (`UploadFile`) are read fully into memory (`get_file_content`, `helpers.py:191-194`: `file.file.read()`), converted to text via format-specific extractors, and only the **extracted text** is persisted — original PDF/DOCX/image bytes are discarded after parsing (except transient temp handling inside the parser, e.g., `pdf_to_entries.py`). There's no `MEDIA_ROOT`/local file directory acting as a document store.
- **Two-tier text storage in Postgres:**
  - `FileObject.raw_text` — the entire file's text, one row per file (full-document store).
  - `Entry.raw`/`Entry.compiled` — the chunked, embedding-bearing rows (retrieval unit), FK'd back to `FileObject`.
- **Object storage is used only for images**, not documents: `src/khoj/routers/storage.py` uploads AI-generated images and user-attached chat images to **AWS S3** (`upload_generated_image_to_bucket`/`upload_user_image_to_bucket`), gated on `AWS_ACCESS_KEY`/`AWS_SECRET_KEY` env vars; disabled (no-op) in self-hosted/local mode. So: text/knowledge goes into Postgres rows; binary image assets go to S3 (with CDN-style bucket-per-domain convention documented at `storage.py:9-13`).
- **File metadata** lives as plain columns on `Entry` (`file_path`, `file_name`, `file_type` enum, `file_source` enum: computer/notion/github, `url`), not a separate metadata table.
- External sources (GitHub, Notion) are pulled server-side via `GithubConfig`/`NotionConfig` credentials stored in the DB and re-fetched/re-indexed on each sync (`processor/content/github/github_to_entries.py`, `notion/notion_to_entries.py`) rather than mirrored to disk.
- A vestigial **local-file / on-disk embeddings cache path** still exists in `search_type/text_search.py` (`compute_embeddings`/`load_embeddings` use `torch.save`/`torch.load` to a `.pt` embeddings file) — this looks like a legacy/offline-CLI code path predating the DB-backed pgvector storage; the live server-side flow (`EntryAdapters.search_with_embeddings`) does not use it.

### 2.3 Retrieval

**Chunking:** `src/khoj/processor/content/text_to_entries.py` (`TextToEntries.split_entries_by_max_tokens`, L61-140) — uses LangChain's `RecursiveCharacterTextSplitter` with separators `["\n\n","\n","!","?",".", " ", "\t", ""]`, `chunk_size=256` tokens (default), no overlap, custom `tokenizer` (whitespace split), heading-prefixing on non-first chunks, and stable `corpus_id` (uuid) shared by all chunks of one logical source entry so results can be traced back to origin. Per-format extraction happens in `processor/content/{org_mode,markdown,pdf,docx,plaintext,notion,github,images}/*_to_entries.py`, each producing `Entry` (Pydantic, `utils/rawconfig.py`) objects consumed by the shared `TextToEntries.update_embeddings` pipeline (L142-263).

**Embeddings:** `src/khoj/processor/embeddings.py` — `EmbeddingsModel` wraps **sentence-transformers** (`SentenceTransformer`) for local embedding, default model `thenlper/gte-small`, or delegates to a **HuggingFace inference endpoint** or **OpenAI embeddings API** depending on `SearchModelConfig.embeddings_inference_endpoint_type`. `embed_documents`/`embed_query` are the two entry points (asymmetric encoding — separate query/doc encode kwargs, `normalize_embeddings=True`).

**Vector storage/search:** Same Postgres DB, via **pgvector** `VectorField` on `Entry.embeddings` and `UserMemory.embeddings`. Similarity search is `django_pgvector`'s `CosineDistance` annotation + `order_by("distance")` + `.filter(distance__lte=max_distance)` — see `EntryAdapters.search_with_embeddings` (`database/adapters/__init__.py:2143-2172`) and `UserMemoryAdapters.search_memories` (L2326-2347). No separate/external vector DB (no Pinecone/Weaviate/Chroma) — pgvector inside the same relational DB is the only vector store.

**Hybrid search:** Yes. `EntryAdapters.apply_filters` (`database/adapters/__init__.py:2084-2141`) layers structured filters on top of vector search:
  - keyword filters via query syntax `+"word"` / `-"word"` → `raw__icontains` (ILIKE) (`search_filter/word_filter.py`)
  - file filters via `file:"glob"` → regex on `file_path` (`search_filter/file_filter.py`)
  - date filters (natural-language date parsing) → joins on `EntryDates` (`search_filter/date_filter.py`)
  These are ANDed with the pgvector cosine-distance ordering in `search_with_embeddings`, so it's closer to "filtered vector search" than true BM25/full-text hybrid — there's no separate keyword/BM25 index (e.g., no Postgres `tsvector`, no Elasticsearch).

**Reranking:** `CrossEncoderModel` (`processor/embeddings.py:117-146`), default `mixedbread-ai/mxbai-rerank-xsmall-v1` via sentence-transformers `CrossEncoder`, or a HF inference endpoint. Invoked conditionally in `search_type/text_search.py:rerank_and_sort_results`/`cross_encoder_score` (only when explicitly requested or an inference server is configured, and only if >1 hit) — results are sorted by cross-encoder score first, falling back to bi-encoder distance.

**Context assembly for LLM:** `src/khoj/routers/api_chat.py` orchestrates: extracts search queries from the user message (`extract_questions`), calls `execute_search`/`text_search.query` per inferred query, collects into `compiled_references` (with dedup via `collate_results`/`deduplicated_search_responses`). This, plus online search results, code-execution results, and retrieved memories, are handed to `processor/conversation/utils.py:generate_chatml_messages_with_context` (L677-851), which builds the final ChatML message list: system prompt → truncated chat history (with each historical turn's note/online/code context re-embedded) → any newly retrieved note context (`prompts.notes_conversation`) → a `<retrieved_memories>` block → the current user message. Token-budget management is explicit: `max_prompt_size` looked up per model (`model_to_prompt_size`), `lookback_turns = max_prompt_size // 750` scales how much history is kept, and `truncate_messages` (same file) trims oldest messages to fit before calling the model.

### 2.4 Memory

Two distinct memory layers, cleanly separated:

- **Short-term / session memory** — the full chat transcript is stored verbatim as JSON in `Conversation.conversation_log` (`database/models/__init__.py:658-701`). `ConversationAdapters.save_conversation` (`database/adapters/__init__.py:1561-1594`) appends new turns (`existing_messages + new_messages`) into this JSONField on every turn — no separate message table, it's a single denormalized JSON blob per conversation. Retrieved back into context wholesale, subject to the token-budget truncation described above.
- **Long-term / cross-session memory** — the `UserMemory` model (embeddings + raw fact text). After every conversation turn, `processor/conversation/utils.py:save_to_conversation_log` calls `ai_update_memories` (`routers/helpers.py:1038-1067`), which:
  1. Skips entirely if `ConversationAdapters.ais_memory_enabled(user)` is false (per-user toggle, `UserConversationConfig.enable_memory`).
  2. Calls `extract_facts_from_query` — an **LLM call** using the `extract_facts_from_query` prompt (`processor/conversation/prompts.py:1306-1371`, persona "Muninn, the user's memory manager") that, given existing facts + the latest chat turn, returns a structured `{create: [...], delete: [ids...]}` diff (Pydantic `MemoryUpdates` schema).
  3. Persists via `UserMemoryAdapters.save_memory`/`delete_memory` (`database/adapters/__init__.py:2303-2361`) — `save_memory` embeds the new fact text and stores it with `embeddings`, `raw`, `search_model`.
  - Retrieval back into context happens two ways, both invoked at the top of `api_chat.py`'s chat generator (L969-975): `pull_memories` (recency-window recall — last N memories updated within `window` days, "medium term") and `search_memories` (semantic recall via pgvector cosine distance against the query, "long term", thresholded by `bi_encoder_confidence_threshold`). The two lists are merged/deduped by id and injected as `relevant_memories` throughout the pipeline (tool/data-source selection, research mode, document search query inference, and finally the `<retrieved_memories>` block in the prompt).
  - This is essentially a self-managed, LLM-driven fact-extraction memory system (similar in spirit to MemGPT/mem0-style designs), built entirely on the same Postgres+pgvector infrastructure as document retrieval, not a separate memory service.
- `ReflectiveQuestion` (a separate small model) stores canned/generated conversation-starter prompts — not memory, but adjacent.

### 2.5 Data flow (ingestion → processing → storage → indexing → retrieval → context → LLM)

1. **Ingress**: `PUT/PATCH /api/content` (`routers/api_content.py:75-116`, `indexer()` at L544) — client (Obsidian/Emacs plugin, desktop app, web upload) sends files as multipart `UploadFile`s, or `GithubConfig`/`NotionConfig` credentials trigger server-side pulls (`processor/content/github/github_to_entries.py`, `notion/notion_to_entries.py`).
2. **Text extraction**: `get_file_content` (`routers/helpers.py:191`) sniffs type/encoding; format-specific parsers in `processor/content/{org_mode,markdown,plaintext,pdf,docx,images}/*_to_entries.py` convert bytes → `Entry` (Pydantic) objects.
3. **Dispatch**: `routers/helpers.py:configure_content` (L3010+) routes per-type file dicts to `search_type/text_search.setup(XToEntries, files, regenerate, user)`.
4. **Chunk/hash/dedupe**: `TextToEntries.process()` (per-type subclass) → `split_entries_by_max_tokens` (chunking) → `update_embeddings` (`processor/content/text_to_entries.py:142`) — MD5-hashes each chunk (`hash_func`), diffs against existing `Entry.hashed_value`s per file to find genuinely new/changed/removed chunks.
5. **Embed**: new chunks batched through `EmbeddingsModel.embed_documents` (`processor/embeddings.py`) — local sentence-transformers or HF/OpenAI endpoint.
6. **Persist**: `FileObjectAdapters.create_file_object`/`update_raw_text` stores full file text; `DbEntry.objects.bulk_create` stores chunk rows with `embeddings` (pgvector column); `EntryDates.objects.bulk_create` indexes extracted dates; stale hashes are deleted (`EntryAdapters.delete_entry_by_hash`).
7. **Query time**: user chat message → `routers/api_chat.py` chat_completion generator → `extract_questions` (LLM call to synthesize search queries) → `search_documents`/`execute_search` (`routers/helpers.py:1288`, `1485`) → `text_search.query` → `EntryAdapters.search_with_embeddings` (pgvector cosine distance + keyword/date/file filters) → optional cross-encoder rerank → `collate_results`.
8. **Context assembly**: retrieved note chunks + recalled `UserMemory` facts + prior turns from `Conversation.conversation_log` + online/code results → `generate_chatml_messages_with_context` (`processor/conversation/utils.py:677`) builds the final message list, truncated to the model's token budget.
9. **LLM call**: dispatched to provider-specific modules `processor/conversation/{openai,anthropic,google}/*.py` (`converse_openai`, `converse_anthropic`, `converse_gemini`).
10. **Write-back**: `save_to_conversation_log` (`processor/conversation/utils.py:541`) appends the turn to `Conversation.conversation_log` and fires `ai_update_memories` to (maybe) extract/persist new long-term `UserMemory` facts, closing the loop.

### 2.6 Notable design patterns / observations (Khoj)

- **Single relational store for everything** — Postgres+pgvector is used uniformly for user data, chat transcripts (as JSON blobs), document chunks+embeddings, and extracted memories+embeddings. There is no polyglot persistence (no dedicated vector DB, no document store, no cache layer beyond an in-process `state.query_cache` LRU per user in `routers/helpers.py`). Simplifies ops (one DB to run/back up) at the cost of JSON-blob conversation storage not being queryable/relational.
- **Adapters layer as a clean data-access boundary** (`database/adapters/__init__.py`) — good separation between Django models and business logic/routers, though the file is very large (2374 lines) and could benefit from splitting per domain module.
- **Content-hash based incremental indexing** (MD5 hash per chunk, diffed per file) avoids full re-embedding on every sync — efficient design for a "personal second brain" that re-syncs the same vault repeatedly.
- **Two-tier memory (session JSON transcript + LLM-curated long-term fact store)** is a notably deliberate design, mirroring emerging "agent memory" patterns (mem0/MemGPT-style), fully self-hosted on the same DB rather than a third-party memory service.
- **Original document bytes are never retained server-side** — only derived text. This is privacy-friendly (matches Khoj's "self-hostable/privacy" positioning, see `documentation/docs/get-started/privacy-security.md`) but means there's no way to re-derive/re-parse a document differently later without the user re-uploading it (worth flagging as a limitation for any "re-processing" or format-migration scenario).
- **Legacy code path**: `search_type/text_search.py` still contains a `torch.save`/`torch.load`-based on-disk embeddings cache (`compute_embeddings`/`load_embeddings`) that appears to be a holdover from an earlier, non-DB-backed design; the live server path uses pgvector exclusively.
- **No dedicated keyword/full-text index** — "hybrid search" here is vector search filtered by simple ILIKE/regex/date predicates, not a real BM25/tsvector hybrid; recall for pure-keyword queries is weaker than in systems with a proper inverted index.

---

## 3. LibreChat Research — MCP Connectivity & Multi-Provider AI Abstraction

**Important context note:** This repo is a heavily extended/enterprise fork of upstream LibreChat — it has far more MCP machinery (OAuth, OBO token exchange, distributed leader/follower registry init, circuit breakers, HITL, triggers, activity labels) than the OSS project. Treat file references below as specific to *this* checkout.

Also note: the actual LangChain model classes and the agentic tool-calling loop live in the external npm package `@librechat/agents` (`api/package.json:49`, not vendored in this repo). LibreChat's own code (this repo) is the **configuration/glue layer**: it resolves credentials, builds provider-agnostic `ClientOptions`, discovers/wraps tools, and hands everything to `@librechat/agents` to actually run.

### 3.1 MCP (Model Context Protocol) Connectivity

**Core module:** `packages/api/src/mcp/` (~130 files, ~12k LOC in core files alone — this is a very large subsystem).

**Config file format/schema:**
- Schema source of truth: `packages/data-provider/src/mcp.ts`. Defines `BaseOptionsSchema` (title, description, `startup`, timeout knobs, `oauth`, `apiKey` (admin- or user-provided), `customUserVars`) extended by four transport variants combined into `MCPOptionsSchema = z.union([StdioOptionsSchema, WebSocketOptionsSchema, SSEOptionsSchema, StreamableHTTPOptionsSchema])` (`mcp.ts:279-406`). `MCPServersSchema = z.record(string, MCPOptionsSchema)` is the `mcpServers:` block of `librechat.yaml`.
  - `stdio`: `command`, `args`, `env` (supports `${VAR}` interpolation), `stderr`, `cwd`.
  - `sse` / `streamable-http`: `url`, `headers`, `obo` (On-Behalf-Of token exchange config), `proxy`.
  - `websocket`: `url` (ws/wss only).
  - **Security-hardened split**: `MCPServerUserInputSchema` (`mcp.ts:464-476`) is a *separate*, stricter schema for user-submitted (UI) servers — stdio is explicitly excluded ("allows arbitrary command execution"), URLs reject `${VAR}` patterns (prevents env-var exfiltration), and admin-only OAuth `audience`/`resource` fields are stripped.
- Runtime env knobs: `packages/api/src/mcp/mcpConfig.ts` — OAuth timeouts, `TOOLS_LIST_MAX_PAGES/TOOLS/BYTES/TIMEOUT` (bounds paginated `tools/list`), idle-connection timeout, and a **circuit breaker** (`CB_MAX_CYCLES`, `CB_CYCLE_WINDOW_MS`, `CB_MAX_FAILED_ROUNDS`, backoff) to stop hammering a flapping server.
- `MCPServerSource` type (`packages/api/src/mcp/types/index.ts:152-162`) tags where a server config came from: `'yaml'` (operator, full trust, boot-time init), `'config'` (admin DB override, full trust, lazy init), `'user'` (UI-submitted, sandboxed placeholder resolution), `'plugin'` (Agent Plugins package). This tag gates which `${PLACEHOLDER}` substitutions are allowed.

**Connection lifecycle / session management:**
- `packages/api/src/mcp/connection.ts` — `MCPConnection extends EventEmitter` (2700 lines) is the per-server transport wrapper. Builds the actual `Transport` (stdio/SSE/WS/StreamableHTTP) via `constructTransport()`, with SSRF protection (private-IP/CIDR blocking, allowed-domain/address lists), proxy support, custom fetch/dispatcher construction, reconnection with backoff, per-server circuit breaker (`isCircuitOpen`, `recordCycle`, `recordFailedRound`), tool-list-changed subscription/refresh (`subscribeToToolListChanges`, `refreshToolList`), and idle/stale detection.
- `packages/api/src/mcp/UserConnectionManager.ts` — abstract base managing **per-user** connection pools (`userConnections: Map<userId, Map<serverName, MCPConnection>>`), connection borrow/lease/refcounting, idle disconnection (`USER_CONNECTION_IDLE_TIMEOUT`), and forced-reconnect queuing.
- `packages/api/src/mcp/MCPManager.ts` — the **singleton facade** (`MCPManager extends UserConnectionManager`, `getInstance()`/`createInstance()`). Distinguishes:
  - **App-level connections** (`this.appConnections: ConnectionsRepository`) — shared, boot-time-initialized servers (`source: 'yaml'`/`'config'` with `startup: true`), one connection shared across all users.
  - **User-level connections** — OAuth-gated or per-user servers, created lazily via `getUserConnection`/`getConnection` (`MCPManager.ts:104-255`).
- `packages/api/src/mcp/ConnectionsRepository.ts` manages the app-level connection pool and staleness checks (config `updatedAt` vs live connection).
- `packages/api/src/mcp/registry/MCPServersRegistry.ts` + `MCPServersInitializer.ts` + `MCPServerInspector.ts`: startup orchestration. Notably implements **cluster leader/follower coordination** (`isLeader()` from `~/cluster`) so only one replica performs the expensive connect+inspect+cache-tools sequence at boot, with followers polling a `RegistryStatusCache` (Redis-backed) until ready (`MCPServersInitializer.ts:44-80`). Registry also resolves servers from three tiers — YAML, admin DB config overrides, user DB-stored servers — merging/aliasing normalized vs raw server names.

**Tool discovery & exposure to the model:**
- `MCPConnection.fetchToolsSnapshot()` / `fetchOrderedToolsSnapshot()` (`connection.ts`) call MCP `tools/list` with pagination guards (page/byte/count/time budgets from `mcpConfig`).
- `packages/api/src/mcp/tools.ts` (`createMCPToolCacheService`) turns raw MCP `Tool[]` into LibreChat's internal `LCAvailableTools` map, keyed as **`${toolName}${mcp_delimiter}${normalizeServerName(serverName)}`** (delimiter `_mcp_`, `packages/data-provider/src/config.ts:2957`) — this composite key is how a single flat tool namespace disambiguates same-named tools across different MCP servers. JSON Schema → normalized/ref-resolved via `packages/api/src/mcp/zod.ts` (`convertJsonSchemaToZod`, handles `oneOf`/`anyOf`, `$ref` pointers). Results are cached (in-memory/Redis, with generation/publication-revision fencing to avoid stale/racy tool-list writes across replicas — see `toolsChanged.ts`, `getMCPAppToolsPublicationGeneration`).
- **Wrapping as a LangChain tool** happens in `api/server/services/MCP.js`:
  - `createMCPTools` / `createMCPTool` (`MCP.js:744-1008`) resolve a tool key back to its server + tool definition (re-triggering discovery/reconnect if the tool isn't cached).
  - `createToolInstance` (`MCP.js:1010-1185`) builds the actual tool via `tool(_call, { schema, name: normalizedToolKey, description, responseFormat: AgentConstants.CONTENT_AND_ARTIFACT })` from `@librechat/agents/langchain/tools`. Notably it **sanitizes the JSON Schema for Google/Vertex** (`sanitizeGeminiSchema`, `MCP.js:1030-1034`) since Gemini rejects unions/non-string enums that OpenAI/Anthropic accept fine — a concrete example of provider-capability handling living at the tool-schema layer, not the core abstraction.

**Auth / per-server config handling:**
- `packages/api/src/mcp/auth.ts`, `oauth/` (18 files): full OAuth 2.1 client (auto-discovery on 401, dynamic client registration, PKCE, token refresh, resource-hint/audience support for Auth0-style providers), plus `oauth/obo.ts` — **On-Behalf-Of token exchange**: LibreChat can exchange the logged-in user's OIDC token for a downstream-scoped token via JWT-bearer grant (`MCPManager.callTool`, `MCPManager.ts:960-998`), gated by an author-permission re-check (`oboTrustChecker`) so a downgraded admin's OBO config stops working automatically.
- Non-OAuth secrets: `apiKey` block (`source: 'admin'` shared key vs `source: 'user'` per-user key) and `customUserVars` (arbitrary named user-supplied placeholders, `sensitive` flag controls UI masking) resolved via `processMCPEnv` (`~/utils/env`) at connection/tool-call time, keyed to request body / user object.
- User-facing management API: `api/server/routes/mcp.js` (1142 lines) — OAuth initiate/callback/bind/cancel/status, connection status polling, server CRUD (`/servers` GET/POST/PATCH/DELETE) gated by `checkMCPUsePermissions`/`checkMCPCreate`, auth-values endpoint for entering `customUserVars`.

**Tool call execution & result formatting:**
- `MCPManager.callTool()` (`MCPManager.ts:774-1161`) is the single execution path: resolves connection (app or user), re-processes env/placeholders per-call, refreshes OBO tokens, attaches an OAuth-recovery handler, sends the JSON-RPC `tools/call` request via the MCP SDK client (`connection.client.request(...)`, `MCPManager.ts:1074-1089`) with the connection's timeout, and on success formats results via `formatToolContent`.
- `packages/api/src/mcp/parsers.ts::formatToolContent` (`parsers.ts:141-254`) converts MCP `content` blocks into `[text, artifacts]`: text/resource blocks flatten into a text block; image blocks become artifacts (size-capped, `assertImageDataWithinLimit`, default 10MB); `ui://` resource URIs become inline `\ui{resourceId}` markers plus a `ui_resources` artifact for the client to render. This is provider-agnostic — per the function's own comment, "All providers receive string content... provider-specific artifact merging is delegated to the agents package."

**Error handling:**
- `packages/api/src/mcp/errors.ts`: `isOAuthAuthenticationError` (401/403 code or message-pattern detection, including SDK-specific `StreamableHTTPError`), `isStandaloneSseConflict` (409 on the standalone SSE GET stream — requires a full transport rebuild, not a retry), typed errors `MCPDomainNotAllowedError`, `MCPInspectionFailedError`, `MCPOAuthSecretReentryRequiredError`.
- In `callTool`, OAuth-class errors trigger `recoverOAuthConnection` (re-auth flow with a shared "recovery lease" so concurrent tool calls on the same connection don't each trigger their own OAuth popup) before retry; other errors are logged and rethrown.
- `createToolInstance`'s `_call` (`MCP.js:1123-1162`) catches everything and rewrites into user-facing messages — OAuth errors become "OAuth authentication required..." (or, if the server has no OAuth configured, "...MCP OAuth is not configured for this server"), everything else becomes `[MCP][server][tool] tool call failed: <message>` — these strings become the ToolMessage content the LLM sees, so the model can react/report the failure rather than the process crashing.

### 3.2 Multi-Provider AI Model Abstraction

**The actual adapter interface** `packages/api/src/types/endpoints.ts:43-65`:
```ts
type InitializeFn = (params: BaseInitializeParams) => Promise<InitializeResultBase>
BaseInitializeParams = { req, endpoint, model_parameters?, db: EndpointDbMethods }
InitializeResultBase = { llmConfig: ClientOptions /* from @librechat/agents */, configOptions?, endpointTokenConfig?, useLegacyContent?, provider?, tools? }
```
Every provider module implements exactly this function shape. This is a clean **Adapter pattern**: each provider normalizes credentials/config into `ClientOptions`, a shape `@librechat/agents` understands generically (it internally maps `provider` → the right LangChain chat-model class: ChatOpenAI, ChatAnthropic, ChatVertexAI/ChatGoogleGenerativeAI, ChatBedrockConverse, etc.).

**Registry / routing (adapter selection):** `packages/api/src/endpoints/config/providers.ts::providerConfigMap` (`providers.ts:40-51`) is a literal **Registry pattern**:
```
XAI, DEEPSEEK, MOONSHOT, OPENROUTER → initializeCustom
VERTEXAI → initializeGoogle   (shares Google adapter; auth-only distinction)
openAI, azureOpenAI → initializeOpenAI
google → initializeGoogle
bedrock → initializeBedrock
anthropic → initializeAnthropic
```
`getProviderConfig({ provider, appConfig })` (`providers.ts:137-219`) is the actual **routing decision function**: looks up the map (case-insensitive fallback), and if the provider string matches none of the built-ins, falls through to `getCustomEndpointConfig` (looks up `endpoints.custom[]` by name in `librechat.yaml`) and defaults to `initializeCustom` (OpenAI-compatible) unless that custom entry declares `provider: anthropic`, in which case it's routed to the native Anthropic `/v1/messages` client instead (`endpoints/custom/initialize.ts:322-334`, `buildAnthropicCustomConfig`).

This function is called from the actual request path in `packages/api/src/agents/initialize.ts:1155-1173` — `agent.provider`/`endpoint` (resolved from the request body / saved Agent document / model spec) is looked up, `getOptions()` is invoked to build `llmConfig`, and `agent.provider` is possibly overridden by what `getOptions` returns (e.g. Azure serverless deployments fall back to `Providers.OPENAI`). Call sites: `packages/api/src/agents/initialize.ts:1155`, `agents/run.ts:561` (summarization/title reuse the same routing), `api/server/controllers/agents/client.js:3859` (title generation), `api/server/services/Endpoints/agents/initialize.js:792`.

**Ollama / NVIDIA NIM / generic OpenAI-compatible endpoints:** There is **no hardcoded Ollama or NVIDIA NIM provider module**. They're configured entirely through `endpoints.custom[]` in `librechat.yaml` (`librechat.example.yaml:649-800`, examples given for Groq/Mistral/OpenRouter/Helicone/Portkey — same mechanism applies to Ollama/NIM: any `baseURL` + `apiKey` OpenAI-compatible server). `initializeCustom` (`packages/api/src/endpoints/custom/initialize.ts:176-353`) resolves admin- or user-provided `apiKey`/`baseURL`, optional model auto-fetch (`fetchModels`), `addParams`/`dropParams` request-shape overrides, and by default calls `getOpenAIConfig` (`endpoints/openai/config.ts`) — i.e. Ollama/NIM/Groq/etc. all go through the **OpenAI adapter** since they speak the OpenAI chat-completions wire format. Custom endpoints set `useLegacyContent = true` (older/simpler content-array format, since many self-hosted/compatible servers don't support OpenAI's newer multimodal content blocks).

**API keys / config storage:**
- Built-in providers: env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) or **user-provided keys** stored via `db.getUserKeyValues` (encrypted at rest, expiry-checked via `checkUserKeyExpiry`) — see `openai/initialize.ts:41-65`. `userProvidesKey`/`userProvidesURL` toggles per-endpoint in `librechat.yaml` (`userProvide: true`) decide which source wins.
- Custom endpoints: `apiKey`/`baseURL` fields in `librechat.yaml`, resolved through `extractEnvVariable` (`${VAR}` interpolation) with the same user-override mechanism.
- Azure: `mapModelToAzureConfig` resolves per-model-group Azure deployment/API-version/headers (`openai/initialize.ts:91-139`).

**Provider-specific capability handling without breaking the abstraction:** Each provider's own `llm.ts`/`helpers.ts` translates a **common, provider-agnostic parameter surface** (`model_parameters` from the request/agent) into that provider's native wire shape, and only that provider's module knows the mapping:
- **Anthropic thinking**: `packages/api/src/endpoints/anthropic/helpers.ts` (~90-190) — maps a generic `thinking`/`thinkingBudget`/`thinkingDisplay` set into Anthropic's native `{type: 'enabled', budget_tokens}` block, handles model-version differences (adaptive thinking on Opus/Sonnet 4.6+ needs explicit `disabled` when off; budget clamped to not exceed `max_tokens`).
- **OpenAI reasoning**: `packages/api/src/endpoints/openai/llm.ts` (~79-183) — maps `reasoning_effort`/`reasoning_summary`/`reasoning_mode`/`reasoning_context` into OpenAI's `reasoning: {effort, summary, mode, context}`, and routes reasoning+tools combos to the Responses API when needed (GPT-5.x rejects function tools with `reasoning_effort` on chat-completions).
- **Google/Gemini schema limits**: `sanitizeGeminiSchema` (referenced from `MCP.js:1033`) flattens JSON Schema unions/non-string enums that Gemini's function-calling can't parse, applied only on the Google code path.
- Net effect: the **outer contract stays uniform** (`InitializeResultBase.llmConfig: ClientOptions`, generic `model_parameters` in/out), while capability differences are absorbed inside each provider's own module — an Adapter/Strategy pattern where the "strategy" also owns quirk-normalization, not just field renaming.

### 3.3 Tool Architecture: Internal/Plugin Tools vs MCP Tools

Explicit taxonomy exists in code: `packages/api/src/tools/registry/definitions.ts:9-16`:
```ts
interface ToolRegistryDefinition {
  ...
  toolType: 'builtin' | 'mcp' | 'action' | 'custom';
}
```
- **`builtin`** — native capabilities implemented via `@librechat/agents` factories (`Calculator`, `createSearchTool`, `createCodeExecutionTool` — imported directly in `packages/api/src/tools/registry/definitions.ts:1`) plus LibreChat-specific ones like the HITL `askUserQuestionTool` (`packages/api/src/agents/hitl/askUserQuestionTool.ts`). These ship with the app; no external process.
- **Legacy "plugin" tools** (pre-agents-registry, still active): `api/app/clients/tools/structured/*.js` — hand-written LangChain `StructuredTool` subclasses (DALLE3, GoogleSearch, TavilySearch, TraversaalSearch, Wolfram, OpenWeather, AzureAISearch, FluxAPI, StableDiffusion, GeminiImageGen, OpenAIImageTools). Registered/described in `api/app/clients/tools/manifest.json` (name, `pluginKey`, `icon`, `authConfig` — a **Registry pattern** with per-tool auth-field metadata used to render the plugin-store UI and validate stored credentials via `PluginService`/`credentials.js`).
- **`mcp`** — discovered dynamically at runtime from external MCP servers (no code shipped with LibreChat), wrapped generically as described in §3.1.
- **`action`** — OpenAPI-spec-defined custom Actions (assistants-style, out of scope here but present in the same registry taxonomy).

**Assembly point — `loadTools` (`api/app/clients/tools/util/handleTools.js:176-...`)** — this is where the two worlds get merged for a given chat turn:
- `toolConstructors` (`handleTools.js:191-201`) — static map of `pluginKey → Tool class` for the manifest-based tools.
- `customConstructors` (`handleTools.js:203-246`) — async factory functions for tools needing per-request setup (image editing context, credential loading).
- MCP tools are detected separately: `hasMCPTools = tools.some(name => mcpToolPattern.test(name))` (`handleTools.js:249`), i.e. any requested tool key containing the `_mcp_` delimiter is routed to `resolveMcpServerContext`/`createMCPTools` (from `~/server/services/MCP`) instead of the static constructor map — MCP tool availability is permission-checked separately (`mcpPermissionContext.canUseServers`) and resolved against the MCP server registry, not the manifest.
- Both categories end up as LangChain `Tool`/`StructuredTool` instances in the same flat array passed to the agent graph — from the model's point of view there is **no distinction**; the difference is entirely in how LibreChat constructs the `_call` implementation (in-process function vs MCP JSON-RPC round-trip).

**Exposure to the model (function-calling schema):**
- MCP: JSON Schema from `tools/list` → normalized/ref-resolved (`packages/api/src/mcp/zod.ts`) → becomes the tool's `parameters` (see §3.1).
- Builtin/plugin: each `StructuredTool` defines its own Zod schema in code (e.g. `dalle3Schema`/`googleSearchSchema` in `packages/api/src/tools/registry/definitions.ts`), or a hand-written Zod schema in the `.js` tool file itself.
- Both funnel into `@librechat/agents`' tool-binding layer, which converts to each provider's native function-calling format (OpenAI `tools[].function`, Anthropic `tools[]` with `input_schema`, Gemini `functionDeclarations`) — this conversion is inside the external package, not this repo.

### 3.4 Overall Flow: LLM → Tools → MCP/External Systems

Request path (agents endpoint, the primary/modern flow):
1. **Route entry**: `api/server/routes/agents/chat.js` (`POST /agents/:endpoint` etc.) → controller → `api/server/services/Endpoints/agents/build.js::buildOptions` (`build.js:9-33`) — resolves the `Agent` document (`loadAgentFn`, aliased to `packages/api/src/agents/load.ts`) and merges request `model_parameters`.
2. **Agent/provider initialization**: `packages/api/src/agents/initialize.ts` — calls `loadTools`-equivalent tool loading (`callLoadTools`, MCP + builtin merge, ~`initialize.ts:1060-1153`), then `getProviderConfig` → provider-specific `initializeXxx` → `llmConfig` (§3.2), producing an `InitializedAgent` (model client config + bound tool list).
3. **Execution**: handed to `@librechat/agents` (external package) which builds the LangGraph agent loop: model call → if the model emits a tool call → **ToolNode** invokes the matching LangChain tool's `_call`.
   - If the tool is a **builtin/plugin tool**: `_call` runs in-process (image gen API call, calculator, web search API, etc.) — external systems only if that specific tool talks to one (e.g. DALL·E/Tavily APIs), but there's no MCP protocol involved.
   - If the tool is an **MCP tool**: `_call` (built in `createToolInstance`, `api/server/services/MCP.js:1049-1163`) calls `MCPManager.callTool()` (`packages/api/src/mcp/MCPManager.ts:774`), which resolves/reuses an `MCPConnection` (`packages/api/src/mcp/connection.ts`) and sends a `tools/call` JSON-RPC request over the configured transport (stdio subprocess / SSE / Streamable HTTP / WebSocket) to the **external MCP server process**, which itself may call further external systems (APIs, databases, filesystems, etc.).
4. **Result formatting**: MCP results → `formatToolContent` (`packages/api/src/mcp/parsers.ts`) → `[text, artifacts]`; builtin tool results → each tool's own `responseFormat: CONTENT_AND_ARTIFACT` return shape. Both become a `ToolMessage` fed back into the model for the next turn.
5. **Errors** at any point (OAuth failure, MCP transport error, tool exception) are normalized into a string ToolMessage content (§3.1 "Error handling") rather than terminating the run, so the model can see and react to the failure (e.g. ask the user to re-authenticate).

Key file map for this flow:
- `api/server/services/Endpoints/agents/build.js` — request → options.
- `packages/api/src/agents/load.ts`, `packages/api/src/agents/initialize.ts` — agent/tool/provider assembly.
- `packages/api/src/endpoints/config/providers.ts` — provider routing table (registry pattern).
- `packages/api/src/endpoints/{openai,anthropic,google,bedrock,custom}/initialize.ts` + `llm.ts` — per-provider adapters.
- `api/app/clients/tools/util/handleTools.js` — legacy/plugin + MCP tool assembly (`loadTools`).
- `api/server/services/MCP.js` — MCP↔LangChain tool bridge (`createMCPTool`, `createToolInstance`).
- `packages/api/src/mcp/MCPManager.ts`, `connection.ts`, `UserConnectionManager.ts`, `ConnectionsRepository.ts` — MCP session/connection lifecycle.
- `packages/api/src/mcp/parsers.ts`, `errors.ts` — MCP result/error normalization.

### 3.5 Notable Design Patterns (LibreChat)
- **Adapter pattern**: `InitializeFn` contract (§3.2) — every provider, built-in or custom, produces the same `{llmConfig, provider, ...}` shape.
- **Registry pattern**: `providerConfigMap` (providers), `manifest.json` (legacy plugin tools), `ToolRegistryDefinition` (builtin tool registry) — all literal lookup tables mapping a key to a factory/config.
- **Facade/Singleton**: `MCPManager.getInstance()` is the single entry point hiding app-vs-user connection complexity.
- **Repository pattern**: `ConnectionsRepository`, `ServerConfigsDB`/`ServerConfigsCache*` (multiple cache backends behind `ServerConfigsRepositoryInterface` — in-memory, Redis single-key, Redis aggregate-key).
- **Leader/follower coordination**: `MCPServersInitializer` uses a cluster leader-election (`~/cluster::isLeader`) so multi-replica deployments don't all hammer MCP servers at boot simultaneously.
- **Circuit breaker**: per-server connect/fail cycle tracking in `connection.ts` and configurable via `mcpConfig.ts`.

### 3.6 Worth Flagging
- **Strong**: The MCP layer is production-hardened well beyond spec compliance — SSRF protection with CIDR/allowlist checks, OAuth 2.1 + OBO token exchange with trust re-checks, tool-list pagination budgets, cache generation-fencing to avoid cross-replica races, and very deliberate error-message rewriting so the *model* gets actionable feedback (e.g. distinguishing "server needs OAuth" vs "OAuth not configured for this server"). The provider abstraction cleanly isolates capability quirks (Anthropic thinking budgets, OpenAI reasoning-vs-tools conflicts, Gemini schema restrictions) inside per-provider modules without leaking into the common interface.
- **Complexity/maintenance risk**: `connection.ts` (2705 lines) and `MCPManager.ts`/`MCPConnectionFactory.ts` (1161/1589 lines) are large single files carrying transport construction, SSRF logic, OAuth recovery state machines, and circuit breakers together — a lot of cross-cutting concern in few files. The dual tool-loading paths (legacy `handleTools.js` manifest tools vs the newer `packages/api/src/tools/registry` `ToolRegistryDefinition`) suggest an in-progress migration/unification that isn't fully complete.
- **Coupling to a closed dependency**: The actual per-provider LangChain model instantiation and the agent tool-calling loop live in `@librechat/agents`, a separate npm package not present in this checkout — full understanding of streaming/tool-binding internals requires that package's source, which wasn't available for this review.

---

## 4. Synthesized PSOK Architecture Design (from the Plan agent)

**Stack note:** this section was originally drafted assuming TS/Bun/Hono/Tauri for PSOK itself. The user has since chosen **Python + React** for PSOK's implementation. Every mention below of Bun/Hono/TS/`@anthropic-ai/sandbox-runtime`-as-a-JS-lib/Tauri-first should be read as "the equivalent Python/React tooling" (FastAPI, SQLAlchemy/SQLModel, `keyring`, APScheduler, official provider SDKs, Python MCP SDK, React+Vite frontend, OS-native sandboxing invoked via subprocess rather than a JS sandbox-runtime package, desktop wrapper deferred). The architectural reasoning (layers, data placement, permission model, ADR list, phase ordering, decision rules) is stack-independent and unchanged.

The repository was empty at design time (confirmed via listing, only `.claude/` present) — this is a from-scratch design synthesized from the three research inputs above plus PSOK's own requirements.

### 4.1 Layer Diagram / Component Breakdown (with correction to the brief)

**The brief's implied ordering is wrong and is corrected here.** Listing Interface → AI Runtime → Agent loop → Skills → Tools → MCP → Local computer/Bash → Integrations → Core Data → Scheduling reads as a linear pipeline. It isn't one. Three corrections:

1. **Agent Loop is a hub, not a pipeline stage.** AI Runtime and the Data/Scheduling layers are *services the loop calls*, not stages before/after it.
2. **Skills, Tools, MCP, Local-computer, and Integrations are not five parallel peers.** Skills are not an independent execution mechanism — they are content that gets *read through* existing tools (Pipali's insight). MCP tools and Integration tools are not peers of "Tools" — they are two *sources* that register into the same flat Tool Registry as builtin tools (LibreChat's insight: from the model's point of view there is no distinction).
3. **Scheduling is not a terminal stage.** It's a deterministic backing service invoked via tools, structurally identical to how Integrations or Data are invoked.

Corrected topology:

```
+---------------------------------------------------------------------+
|  INTERFACE LAYER  (React SPA / future desktop wrapper / voice)      |
|  transport-agnostic to everything below (WS/HTTP to backend)        |
+------------------------------------+----------------------------------+
                                      |
+-------------------------------------v----------------------------------+
|  AGENT LOOP  ("Director") - THE hub, single owner of the               |
|  reason->act->observe cycle. Assembles prompt (skills catalog +        |
|  tool catalog + retrieved memory/docs + history), calls AI             |
|  Runtime, dispatches tool calls, persists trajectory.                  |
+-------+---------------------------------+-----------------------+------+
        | calls                           | calls                 | calls
        v                                 v                       v
+---------------+   +---------------------------------+   +------------------+
|  AI RUNTIME    |   |   TOOL REGISTRY / DISPATCH       |   |  RETRIEVAL /     |
|  (provider     |   |  (one flat namespace,            |   |  MEMORY SERVICE  |
|  adapters:     |   |   ConfirmationService gate)      |   |  (queries Data   |
|  OpenAI/       |   |                                   |   |   layer)         |
|  Anthropic/    |   |  sourced from:                    |   +------------------+
|  Google/Ollama/|   |   - Builtin Tools (fs/shell/       |
|  OpenAI-compat)|   |     desktop/scheduling)            |
+----------------+   |   - Integration Tools (Gmail/      |
                      |     Calendar/GitHub/...)           |
       ^              |   - MCP Tools (external procs)     |
       | reads via    +-----------+-------------------------+
       | view_file                | dispatches to
+------+--------+    +------------v----------+  +----------------+  +--------------+
| SKILLS         |    | LOCAL COMPUTER         |  | INTEGRATIONS    |  | MCP SERVERS   |
| (SKILL.md dirs,|    | CONTROL                 |  | (Gmail/Cal/     |  | (external,    |
| not a separate |    | (fs/shell/desktop,      |  | GitHub/WA/IG:   |  | 3rd-party or  |
| execution path)|    | sandbox+confirmation)   |  | tools+auth+sync)|  | bundled)      |
+----------------+    +-----------+-------------+  +--------+--------+  +---------------+
                                   |                          |
                                   v                          v
                      +--------------------------------------------------+
                      |  SCHEDULING ENGINE (deterministic)                |
                      |  called via create_task/find_free_slot tools      |
                      +---------------------+------------------------------+
                                            v
                      +--------------------------------------------------+
                      |  DATA LAYER (three mechanisms, not one):          |
                      |  - SQLite (+sqlite-vec, +FTS5): app state,        |
                      |    tasks, calendar, conversations, docs index,    |
                      |    embeddings, memories, integration state,       |
                      |    execution logs                                  |
                      |  - Local filesystem: original documents/vault     |
                      |  - OS keychain: all secrets/credentials            |
                      +--------------------------------------------------+
```

Everything under "Tool Registry" is reached the same way by the Agent Loop; Skills are drawn feeding *into* Tools (they consume the fs/shell tools), not beside them.

### 4.2 Definitions: Tool vs Skill vs MCP Tool vs Integration vs Agent

- **Tool** — a single, atomic, in-process capability with a fixed JSON-Schema contract (`read_file`, `run_shell_command`, `create_task`, `search_memory`). Stateless w.r.t. the loop; any state it needs is passed as args or fetched internally from the Data layer.
- **Skill** — *not* a new execution primitive. A packaged directory (`SKILL.md` + optional `scripts/` + `references/`) teaching the model a multi-step *procedure* that recombines existing Tools. Discovered via progressive disclosure (name+description in the system prompt), read in full via the ordinary `view_file` tool, executed via the ordinary `run_shell_command`/`view_file` tools. No dedicated `invoke_skill` tool.
- **MCP Tool** — a Tool whose implementation lives in an external process PSOK does not own, reached over stdio/SSE/streamable-http. Registered in the same Tool Registry with a namespaced key and results normalized to the same shape as builtin tool results before the Agent Loop ever sees them.
- **Integration** — a first-party module wrapping one external SaaS account (Gmail, Google Calendar, GitHub, WhatsApp, Instagram) that is a *superset* of a Tool: it owns Tools + an auth/credential lifecycle + (often) a background sync worker that materializes external data into PSOK's local SQLite tables so it can be cross-referenced with tasks/calendar/memory. From the model's perspective an integration tool call looks identical to a builtin tool call; the extra machinery lives underneath, not in the model-facing contract.
- **Agent** — reserved for a future concept (a named persona bundling a system-prompt slice + curated tool/skill subset + default model, à la Khoj's `Agent`). **PSOK v1 ships exactly one Agent** — the single Agent Loop with the full catalog. Multi-agent/sub-agent delegation is explicitly out of scope for v1 (flagged in the roadmap, not built now) to avoid overbuilding.

**Decision rule** (cheapest/safest first):
1. Deterministic operation against a local resource PSOK's own backend can implement directly (fs, shell, local DB, scheduling)? → **Builtin Tool.**
2. Multi-step procedure that only recombines *existing* tools, no new code, mostly instructions/templates? → **Skill.**
3. Access to a specific personal external account whose data needs local sync/cross-referencing (tasks, calendar, mail) or whose credentials need PSOK's unified lifecycle? → **Integration.**
4. A capability with a good pre-existing MCP server, used as an on-demand remote capability with no need to persist data locally (browser automation, ad-hoc web APIs, niche one-offs)? → **MCP server.**
5. Needs a fundamentally different reasoning strategy/persona running semi-independently? → **(Future) Agent** — not v1.

### 4.3 AI Runtime Design

**Provider adapter contract** (LibreChat's `InitializeFn`, scaled down): each adapter module implements
`initialize({ providerConfig, modelParameters }) -> { chatModelFactory, capabilities, normalizeParameters, provider }`.
Each adapter owns translation of PSOK's common `ModelParameters` (temperature, maxTokens, reasoningEffort, thinkingBudget, tools[]) into that provider's native wire shape, and declares `capabilities` (tools/streaming/vision/context window). Provider-specific quirks (Gemini's function-calling schema sanitization, Anthropic thinking-budget mapping, OpenAI reasoning-effort/tool-use interplay) are fully absorbed inside the adapter — the Agent Loop and Tool Registry never see them, they always deal in one JSON-Schema tool representation.

**Registry + fallback:** `providerRegistry: {openai, anthropic, google, ollama}` builtins. Any provider name *not* in the registry is looked up in a user-editable `providers.yaml` (`{name, baseURL, apiKey, provider: 'openai-compatible'}`) and routed to a generic OpenAI-compatible adapter by default. This is how NVIDIA NIM, Groq, OpenRouter, vLLM, LM Studio, and self-hosted models get supported without bespoke code.

**Ollama specifically:** just another `providers.yaml` entry pointing at `http://localhost:11434/v1` through the OpenAI-compatible adapter (Ollama already speaks OpenAI chat-completions) — not a bespoke adapter, unless Ollama-native management calls (model pull/list, native embeddings) are needed, in which case a thin `ollama` adapter extends the OpenAI-compatible one just for those extras.

**No LangChain dependency.** PSOK's needs (one active conversation, no chain composition) don't warrant that abstraction tax. Use each vendor's official SDK directly (`openai`, `anthropic`, `google-genai` in Python) behind the `ProviderAdapter` interface defined above; that interface *is* PSOK's abstraction boundary.

**Credentials:** provider API keys live in the OS keychain (macOS Keychain / libsecret / Windows Credential Manager, via Python's `keyring` library), referenced by name from `providers.yaml`. This replaces LibreChat's per-user-encrypted-DB-key scheme, which is multi-tenant machinery PSOK doesn't need.

**Runtime switching:** `provider:model` is a string field on the Conversation record; the Agent Loop resolves the adapter fresh each turn — switching providers mid-conversation is changing a string, no restart.

**Agent Loop ("Director") — single owner of the reason->act->observe cycle:**
1. Assemble system prompt = persona + skills catalog (progressive disclosure) + tool catalog (flat, namespaced) + retrieved memory/doc context (token-budgeted) + conversation history (oldest-truncated-first).
2. Call the active provider adapter with prompt+tools.
3. On tool calls: dispatch through the unified Tool Dispatcher (permission check -> execute -> normalize -> truncate if oversized, e.g. Pipali's 100k-char cap).
4. Append results, loop until plain-text answer, max-turn guard, or a call needs user confirmation (pause).
5. Persist the full trajectory (Pipali's ATIF-style JSON) into `execution_logs`/`messages` for auditability.

Tool calls within a turn execute **sequentially by default** (parallel is an opt-in config flag) — a deliberate simplification vs. Pipali: for a single-user local system, parallel shell/fs mutations raise correctness risk (file races) for little benefit at v1 scale.

### 4.4 Local Computer / Shell / Filesystem Design

Adopt Pipali's ConfirmationService + sandbox-mode pattern, right-sized for solo use.

**Keep as-is:**
- Single `ConfirmationService` gating dangerous ops (`write_file`, `delete_file`, `edit_file`, `run_shell_command`, `desktop_action`, `mcp_tool_call`, `read_sensitive_file`), risk low/medium/high, "don't ask again" persisted per `operation[:subtype]` in a SQLite `confirmation_preferences` table (not just in-memory).
- Sensitive-path denylist (`.ssh`, `.aws`, `.env`, the credential store path itself) forcing confirmation regardless of sandbox.
- Sandbox vs. direct execution modes for shell via OS-native sandboxing (macOS Seatbelt / Linux Bubblewrap, invoked as subprocess wrapping rather than the JS `@anthropic-ai/sandbox-runtime` package Pipali uses — Python equivalent tooling to be selected at implementation time) — with declarative allow/deny read/write paths + allowed network domains in a `sandbox.yaml`.
- Background execution mode (log file + pid, polling, SIGTERM->grace->SIGKILL), but with concurrency capped lower (3-5, not 10) for personal-scale use.

**Judgment calls - modified from Pipali:**
- **Windows sandbox:** explicitly **dropped for v1.** Windows posture is direct-execution + confirmation-only (no fake sandboxing). Revisit later; WSL2-as-sandbox-substitute is a roadmap note, not a v1 requirement.
- **Self-reported model risk classification:** **demoted from primary to a refinement.** A static table (tool/operation -> risk level, e.g. `write_file`=medium, `delete_file`=high, `run_shell_command`=high-unless-sandboxed, `gmail_send`=high, `gmail_search`=low) sets a *floor*. The model's self-reported `operation_type` (still needed for shell command strings and opaque MCP calls, where static analysis is genuinely infeasible) can only **escalate** confirmation requirements, never bypass the floor. This closes Pipali's own identified weakness (trusting model honesty) while keeping its practical value where static analysis can't reach.
- **MCP outside sandbox:** accepted risk (documented in a threat-model doc), *plus* an added guardrail cheap for PSOK to add since it controls MCP config end-to-end: require confirmation on the **first call to any newly configured MCP server**, regardless of self-reported risk, establishing trust once per server. This is orthogonal to, not competing with, the per-call risk-floor gate.
- **Desktop actions:** scope down hard. Implement only `open_application`/`open_url`/`open_file` (OS default-handler launch) for v1. Full screen-reading/click-based GUI automation ("computer use") is explicitly **deferred** (ADR-015) — it's the highest-risk, highest-complexity surface, and none of the brief's concrete examples (tasks/calendar/Gmail/fs/shell/model delegation) require it.

**Filesystem tools:** adopt Pipali's set directly (`view_file`/`list_files`/`grep_files`/`edit_file`/`write_file`), scoped by default to a configured workspace root (a "vault" directory, analogous to a PKB vault); escaping it requires confirmation.

### 4.5 Skills Design

- **Format:** `~/.psok/skills/<name>/SKILL.md` (frontmatter: `name`, `description`, `version` semver, `tags[]`, optional `requires_tools[]`) + markdown body + optional `scripts/` (run via `run_shell_command`) + optional `references/` (read via `view_file`/`grep_files`) + optional `package.json`-equivalent (`requirements.txt`/`pyproject.toml` fragment) for auto-installed script deps.
- **Storage/versioning:** directory name = skill id; `version` is for humans/changelog, discovery keys off the directory. **No remote skill registry/marketplace for v1** — unnecessary infrastructure for a solo project. Builtin skills ship in-repo under `skills/builtin/`, copied to `~/.psok/skills/` on first run without overwriting user edits (Pipali's pattern, kept as-is).
- **Discovery:** scan `~/.psok/skills/*/SKILL.md` at startup, validate frontmatter, cache `{name, description, path}`, inject as compact list into the system prompt. Same progressive-disclosure pattern as MCP tool-search - one mechanism, two applications, per Pipali's own design lesson.
- **Invocation:** deliberately no dedicated tool. Model reads the full `SKILL.md` via `view_file` when relevant, then follows the procedure with ordinary tools. Keeps the tool list small (context budget) and authoring trivial (drop a markdown file in, no registration step).
- **Composition:** skills are expected to combine multiple tools/integrations/MCP calls - that's their entire purpose.

### 4.6 MCP Strategy

**Keep (real value even single-user):**
- Config schema: `mcpServers:` YAML, discriminated union over transport - stdio, SSE, streamable-http. **Drop websocket** - LibreChat hedges across 4 transports for enterprise breadth; PSOK doesn't need that from day one, add later if a real server requires it.
- SSRF protection on URL-based transports (private-IP/CIDR blocking) - protects against a malicious/compromised remote MCP URL reaching internal network services.
- Composite tool-key namespacing (`toolName__mcp__serverName`) to prevent collisions once >1 server is configured.
- Uniform result normalization (`[text, artifacts]`) before results reach the Agent Loop.
- Per-server circuit breaker to stop hammering a flapping server.

**Collapse to a single trust tier.** LibreChat's admin/config/user/plugin four-tier split exists because admin and end-user are different people in a multi-tenant product. In PSOK they're the same person. **Two simple categories, both full-trust:** `configured` (anything in the user's own `mcp.yaml`, stdio allowed, `${VAR}` interpolation allowed) and `bundled` (first-party-recommended servers PSOK ships templates for, e.g. `chrome-devtools-mcp`, offered on first run). No "sandboxed user-submitted via UI" tier - there's no separate untrusted submitter to defend against.

**Explicitly drop:** OAuth 2.1 on-behalf-of token exchange, per-user connection-pool refcounting (one user, one pool), cluster leader-election / Redis-backed shared caches, admin-DB-override tier. If a server needs OAuth, support plain single-user OAuth2 authorization-code login once per server, token stored in the same credential store as Integrations use - not the OBO downstream-scoped-token machinery.

**Decision rule vs. builtin/Integration** (ties to §4.2): default to builtin/Integration when PSOK needs the data persisted locally or it's core to PSOK's own data model (tasks, calendar, mail, fs, shell); reach for MCP for on-demand capability best delegated externally with no local persistence need (browser control, ad-hoc web APIs, niche services).

### 4.7 Data Architecture

**Rejecting Khoj's "one Postgres+pgvector for everything"** as the wrong shape for PSOK's deployment: Postgres is a client-server database meant to be administered, and PSOK is a local-first single-user desktop-ish app with no ops team. **Rejecting the opposite extreme too** (many different database engines) as needless complexity. The resolution: **one embedded engine (SQLite) cleanly separated by domain table, plus exactly two other mechanisms chosen because SQLite is actively wrong for that data type.**

| Data type | Store | Reasoning |
|---|---|---|
| App state / settings / confirmation prefs | SQLite (`app_settings`, `confirmation_preferences`) | Small, relational, needs transactional integrity |
| Tasks | SQLite `tasks` (id, title, due_at, scheduled_at, duration_estimate, status, priority, source, linked_calendar_event_id) | Needs relational queries (overdue, today's schedule) - wrong fit for JSON blob or vector store |
| Calendar | SQLite `calendar_events`, FK-linkable to `tasks`, carries `external_id`/`etag`/`last_synced_at` | Mirrors Google Calendar via sync; conflict-aware sync needs relational identity |
| Conversations | SQLite `conversations` + `messages` (one row per message, tool_calls/tool_results as JSON columns) | **Explicit upgrade over Khoj's single-JSON-blob-per-conversation** - queryable history, incremental token-budget truncation without deserializing a giant blob |
| Documents (original files) | **Local filesystem** (user's configured vault dir) is source of truth; SQLite `documents` is an *index* (path, content_hash, type, size, mtime) pointing at it | **Explicit upgrade over Khoj's "text-extract-only, discard original"** - PSOK is a *personal knowledge base*, keeping originals avoids losing re-derivability and avoids bloating a DB file with binary content |
| Embeddings | SQLite + `sqlite-vec` extension, `document_chunks` (chunk_text, embedding, content_hash for incremental re-index, heading_path) and `memory_embeddings` | Embeddings are coupled to relational chunk metadata; same engine, distinct tables - logical separation, not physical, chosen for zero-ops. **Documented scaling escape hatch:** swap to LanceDB/Qdrant-embedded past roughly 1-5M vectors, if ever needed |
| Memories (long-term facts) | SQLite `memories` (fact_text, embedding, source_conversation_id, status active/superseded) | Khoj's two-tier pattern, see §4.8 |
| Credentials (provider keys, OAuth tokens) | **OS keychain**; SQLite only holds a `credentials` *metadata* row (id, name, secret_ref, scopes, expires_at) - never the secret value | Secrets-in-a-DB-file is a real risk even "encrypted at rest"; this satisfies the "isolated credentials" self-check concretely |
| Integration metadata | SQLite `integrations` + `integration_state` (sync cursors, webhook ids, rate-limit state), separate from `credentials` | Different lifecycle from secrets |
| Execution logs | SQLite `execution_logs` (conversation_id, tool_name, source, args, result, risk_level, confirmation_decision, timestamps) | Needed for auditability; kept out of `messages` because retention/pruning policy differs |

Three storage mechanisms total, each chosen because the others are actively wrong for that data type.

### 4.8 Retrieval / Memory Design

- **Chunking:** adopt Khoj's approach - recursive text splitter, ~256-512 token chunks, heading-prefixed (important since most PKB content is markdown notes), minimal overlap.
- **Embeddings:** default **local** (matches the local-first/privacy posture of a personal knowledge base) via an Ollama-served embedding model (e.g. `nomic-embed-text`) - reuses the runtime PSOK already needs for local chat, no second local-inference dependency. Configurable to a cloud embedding API through the same provider-adapter registry from §4.3 - not a parallel system.
- **Hybrid search - concrete upgrade over Khoj:** vector search (`sqlite-vec`) ANDed with **SQLite FTS5** for genuine inverted-index keyword/BM25-style recall (Khoj's "hybrid" was really just vector + `ILIKE`, no real keyword index). Combine via reciprocal-rank fusion or score blending; metadata filters (date range, path glob, tags) as SQL WHERE on the chunks table.
- **Reranking:** optional local cross-encoder, flagged as a v1.x nice-to-have, not a v1 requirement - hybrid search alone already improves on Khoj's baseline; don't overbuild.
- **Context assembly:** Khoj's pattern - `extract_search_queries` LLM sub-call -> retrieval per query -> dedupe/merge -> token-budgeted `<retrieved_context>` injection, oldest-truncated-first history. Lives inside the Agent Loop's prompt-assembly step (a `RetrievalService`). *Also* expose an explicit `search_documents` tool for on-demand re-query mid-conversation - unlike Khoj, a PKB assistant benefits from both automatic pre-fetch and explicit search.
- **Two-tier memory:** adopt directly. Tier 1 = `messages` table (session/working memory). Tier 2 = `memories` table, populated by a post-turn (or batched every N turns, for cost control) LLM fact-extraction call returning a `{create, supersede}` diff (Khoj's Muninn pattern), retrieved via recency + semantic recall, merged/deduped, injected as `<memories>`. Per-conversation toggle to disable extraction. Fact-extraction model is configurable independently of the main conversation model (reusing the same provider registry) for cost control.

### 4.9 Integrations Design

Each integration (Gmail, Google Calendar, GitHub, WhatsApp, Instagram) is a self-contained module under `integrations/<name>/` implementing a common `IntegrationModule` interface: `{name, authFlow, tools[], syncJob?}`, registered centrally in `integrations/registry`. This is the concrete answer to "can new integrations be added without rewrite" - implement the interface, register it, done.

- **Tools:** each integration contributes ordinary Tools into the flat Tool Registry (`gmail_search`, `gmail_send`, `calendar_create_event`, `github_create_issue`) - from the model's perspective, indistinguishable from any other tool.
- **Auth:** OAuth2 (Google, GitHub) or the service's own token flow (WhatsApp Business API, Instagram Graph API), writing into the shared OS-keychain credential store - never into SQLite or logs. `execution_logs` args/results must be redacted for known credential-shaped fields before persisting.
- **Sync strategy - differs per integration deliberately:** Gmail and Google Calendar get background sync workers (scheduled via the Scheduling Engine itself - dogfooding §4.10) that upsert into `email_index`/`calendar_events` using Khoj's content-hash/etag incremental pattern, because local caching lets PSOK cross-reference mail/calendar with tasks and memory without a live API round-trip every turn. GitHub is mostly **live calls, no local cache** - issue/PR state changes fast and isn't needed for scheduling cross-referencing.
- **Are integrations "just tools" or a distinct layer?** Both, precisely: same Tool Registry surface as builtins (no special-casing for the model), but a distinct *implementation-layer* module type (`integrations/*` vs `tools/builtin/*`) because they carry lifecycle plain tools don't - auth, sync, rate-limiting, external-SLA error handling.

### 4.10 Scheduling Design

**Principle:** the LLM does *interpretation* (extract intent/entities/constraints from NL); a deterministic **SchedulingEngine** does *computation* (date math, conflict checking, recurrence). The model never computes a persisted timestamp itself.

**Flow for "Finish my ML assignment tomorrow":** the Agent Loop recognizes a scheduling-shaped request and calls `create_task` with structured, still-fuzzy args extracted by the model: `{title, due_date_hint: "tomorrow", duration_estimate?, priority?}`. The **tool implementation** (not the model) resolves `"tomorrow"` deterministically against the system clock/user timezone (via a date-parsing library, e.g. `dateparser`/`parsedatetime` in Python, never LLM arithmetic), checks `calendar_events` for conflicts, and either writes a resolved `tasks` row directly or returns a structured ambiguity/conflict description back through the loop so the model can ask the user or propose alternatives - a round-trip through the agent loop, never a tool silently guessing.

**SchedulingEngine module** owns: relative-date resolution, recurrence (RFC 5545 via `python-dateutil`'s `rrule`), free/busy conflict detection against `calendar_events`, and (v1 scope) a simple greedy `find_free_slot` scan. **Deferred explicitly:** full constraint-solver multi-task auto-scheduling - scope control, not a v1 requirement.

**Data model:** `tasks` (§4.7) with `due_at` (deadline) distinct from `scheduled_at` (when you'll actually work on it), `status` enum, optional `calendar_event_id` once materialized onto the calendar.

**Interaction pattern:** the Agent Loop never touches `tasks`/`calendar_events` directly - always through `create_task`/`update_task`/`find_free_slot` tools, subject to the *same* confirmation gating (creating/moving calendar events = medium-risk write per §4.4's static table) and the same result-normalization/logging as every other tool call. Scheduling is just another Tool-Registry capability, not a special-cased subsystem the loop has bespoke knowledge of.

### 4.11 ADR List (18)

1. **AI Provider Abstraction** - Adopt a provider-adapter registry with an OpenAI-compatible fallback for unlisted providers (incl. Ollama/local), instead of hardcoding per-provider integration.
2. **Primary Database Engine** - Use embedded SQLite, not client-server Postgres, for local-first single-user zero-ops operation.
3. **Vector Storage** - Use `sqlite-vec` inside the same SQLite database; document a dedicated local vector engine (LanceDB/Qdrant-embedded) as a scaling escape hatch, not a v1 requirement.
4. **Storage Architecture / Multi-Store Split** - Split data across exactly three mechanisms (SQLite, local filesystem, OS keychain), each justified by what the others are actively wrong for.
5. **Tool Architecture** - Unify builtin, integration, and MCP tools behind one flat Tool Registry/JSON-Schema contract; source differences live only in implementation modules.
6. **Skills Architecture** - Represent skills as filesystem directories discovered via progressive disclosure, invoked through existing fs/shell tools, no dedicated invoke tool, no remote registry.
7. **MCP Strategy** - Single full-trust "configured/bundled" tier (no admin/user split), stdio+SSE+streamable-http, SSRF protection, composite namespacing; excludes OAuth-OBO and multi-tenant pooling.
8. **Integration Architecture** - Each external service is a self-contained module implementing a common `IntegrationModule` interface (tools + auth + optional sync), registered centrally.
9. **Local Computer/Shell Execution & Permissions** - Single ConfirmationService with a static risk floor refined-only-upward by self-reported risk, plus OS-native sandboxing on macOS/Linux and confirmation-only on Windows.
10. **Scheduling Architecture** - LLM interprets NL, but all date math/conflict detection/recurrence run deterministically inside a dedicated SchedulingEngine, invoked only via tools.
11. **Authentication** - v1 is single-user/local with OS-level access control; no login/session auth system until a networked/remote-access phase exists.
12. **Credential Storage** - All API keys and OAuth tokens live in the OS-native secret store, never in SQLite or config files.
13. **Local-First AI Default Posture** - Prefer local models (via Ollama) for embeddings/memory-extraction by default; for the main conversational/tool-calling model, capability requirements are explicitly allowed to override the local-first default (first-run setup detects and prompts accordingly rather than silently defaulting to a possibly-incapable local model).
14. **Background Jobs** - A single in-process lightweight scheduler (APScheduler in Python) handles sync/reminders/memory batching; no external queue/broker (no Redis/Celery-broker) for v1.
15. **Desktop/GUI Automation Scope** - v1 desktop tools are limited to `open_application`/`open_url`/`open_file`; full screen-reading/click automation is deferred to a later, separately-risk-gated phase.
16. **Agent Loop Ownership & Concurrency** - One AgentLoop component owns the per-turn cycle; tool calls execute sequentially by default, parallel is opt-in, to avoid local fs/state races.
17. **Conversation/Message Persistence Model** - Normalized per-message rows, not one JSON blob per conversation, for queryability and incremental token-budget truncation.
18. **Memory Architecture** - Two-tier memory (session transcript + LLM-curated long-term facts table), not no persistent memory and not an external memory service.

### 4.12 Phased Roadmap (dependency-ordered from empty repo)

**Phase 0 - Scaffolding.** (Originally: TS on Bun+Hono. Superseded: Python on FastAPI + React/Vite frontend.) `better-sqlite3`/`bun:sqlite` superseded by `sqlmodel`/SQLAlchemy + `aiosqlite`, pytest, GitHub Actions CI, directory skeleton matching §4.1. *No tests/acceptance beyond "CI green on empty scaffold."*

**Phase 1 - Data layer foundations.** SQLite schema/migrations for all tables in §4.7, a migration runner (Alembic), a repository/adapter layer (Khoj's pattern: callers never touch raw SQL/ORM directly), OS-keychain wrapper module (`keyring`). *Tests:* migration up/down, repository CRUD round-trips. *Acceptance:* DB migration produces a working local DB file; repo unit tests pass. *Why first:* everything downstream persists through this.

**Phase 2 - AI Runtime.** `ProviderAdapter` interface + registry, OpenAI/Anthropic adapters, OpenAI-compatible fallback (covers Ollama immediately), `providers.yaml` loading, keychain-backed key resolution. *Tests:* adapter unit tests (mocked HTTP), live smoke test against local Ollama + one cloud provider. *Acceptance:* single non-tool chat message works through >=2 configured providers, switchable via config with no code change. *Why second:* nothing to call the loop with otherwise.

**Phase 3 - Minimal Agent Loop + Tool Registry.** `AgentLoop` with prompt assembly (empty catalogs initially), single-turn call, tool-call detection scaffold, Tool Registry (register/list/dispatch) with one toy tool. Trajectory persisted to `execution_logs`/`messages`. Minimal FastAPI HTTP/WebSocket entrypoint. *Tests:* loop terminates on plain text; loop incorporates a tool result; max-turn guard fires. *Acceptance:* ask-a-question and ask-something-needing-the-toy-tool both work end-to-end via >=1 provider. *Why third:* this is the spine everything else (skills, real tools, MCP, integrations, scheduling) attaches to.

**Phase 4 - Local computer tools + Confirmation/Sandbox.** fs actor tools, `shell_command` tool, `ConfirmationService` (static risk table + persisted skip-keys), sandbox integration (subprocess-wrapped OS-native sandboxing) with direct-mode fallback, sensitive-path denylist, background execution mode. *Tests:* confirmation gating per risk level, sandbox path-restriction (Linux/macOS CI), shell timeout/kill. *Acceptance:* model can read/write files and run shell within the workspace; dangerous ops pause for confirmation; sandbox measurably restricts fs/network. *Why fourth:* the brief's highest-value capability, self-contained, and proves the confirmation/risk pattern later phases (scheduling writes, integration sends) reuse.

**Phase 5 - Skills.** Discovery/validation, progressive-disclosure injection, builtin-skill seeding, script dep auto-install, 2-3 real builtin skills exercising Phase 4 tools. *Tests:* discovery/validation unit tests, integration test of model correctly following a SKILL.md. *Acceptance:* dropping a new SKILL.md into `~/.psok/skills/` makes it usable with no code change. *Why fifth:* needs Tool Registry + fs tools; low-risk validation milestone before heavier MCP/Integrations work.

**Phase 6 - Retrieval + Documents (vault indexing).** Chunking, content-hash incremental indexing, local/cloud embedding via the Phase 2 adapters, `sqlite-vec` population, FTS5 hybrid search, `search_documents` tool, context-assembly in the Agent Loop. *Tests:* chunking correctness, incremental-reindex-only-touches-changed-chunks, retrieval smoke tests, token-budget truncation. *Acceptance:* pointing PSOK at a notes folder makes it queryable; editing one file re-embeds only its changed chunks. *Why sixth:* PKB's core value; lands before peripheral integrations.

**Phase 7 - Memory.** Post-turn fact extraction, recency+semantic recall (reusing Phase 6 infra), `<memories>` injection, per-conversation toggle. *Tests:* extraction diff logic, recall merge/dedupe. *Acceptance:* a fact stated in one conversation is recalled unprompted in a later, separate one. *Why seventh:* deliberately reuses Phase 6's embedding/vector infra rather than duplicating it.

**Phase 8 - Scheduling Engine + Tasks/Calendar (local-only).** `create_task`/`update_task`/`list_upcoming`/`find_free_slot`, deterministic NL-date resolution, conflict detection against the local calendar cache, confirmation gating reusing Phase 4. *Tests:* date-resolution (timezones, relative phrases), conflict detection, full "Finish my ML assignment tomorrow" integration test. *Acceptance:* the brief's example works end-to-end with a correctly resolved, persisted, confirmable task. *Why eighth:* independent of MCP/Integrations; lands one of the brief's concrete requirements before the heavier external-integration phase.

**Phase 9 - MCP connectivity.** `mcp.yaml` loader, stdio/SSE/streamable-http clients (Python MCP SDK), SSRF protection, namespacing, result normalization, circuit breaker, first-run per-server confirmation, registration into the Phase 3 Tool Registry. *Tests:* transport connection (mock server), namespacing collision, SSRF-blocked-URL, circuit-breaker trip. *Acceptance:* a real third-party MCP server's tools appear alongside builtins, correctly namespaced and normalized. *Why ninth:* extends the system; lower priority than PSOK's own core loop per the brief's emphasis.

**Phase 10 - Integrations (Gmail, Google Calendar, GitHub first).** `IntegrationModule` interface + registry, OAuth2 flows into the keychain, Gmail tools + sync worker, Calendar sync (now feeding Phase 8's conflict detection with real data), GitHub tools (mostly live calls). React frontend wired to the backend by this point. *Tests:* mocked OAuth flow, incremental-sync (etag/hash), credential-redaction-in-logs. *Acceptance:* Gmail search works from the agent; Calendar sync populates `calendar_events` and `find_free_slot` reflects real external events; GitHub issue creation works. *Why tenth:* highest external-dependency surface (OAuth apps, third-party quotas); correctly benefits from every prior phase existing.

**Phase 11 (stretch, roadmap only, not detailed):** Desktop wrapper (Tauri/Electron) polish, full GUI/computer-use automation (per ADR-15), sub-agent orchestration, reranking, constraint-solver auto-scheduling, WhatsApp/Instagram, remote/multi-device access (would require revisiting ADR-11).

### 4.13 Final Architecture Review Self-Check (with contradictions surfaced and resolved)

Coverage check: multiple providers (§4.3, ADR-1), local models (§4.3, ADR-13), tools/skills/bash/MCP/external services (§4.2-4.9), new integrations without rewrite (`IntegrationModule` interface, ADR-8), appropriate data placement (§4.7, ADR-4), deterministic scheduling (§4.10, ADR-10), appropriate AI permissions (§4.4, ADR-9), isolated credentials (§4.7/§4.9, ADR-12), auditable tool execution (`execution_logs`, Phases 3-4), clear boundaries (§4.2), simple enough for solo (no Postgres server/Redis/cluster/OBO - ADRs 7/11/14), no unneeded infra (explicit drops throughout).

**Desktop scope note (not a gap):** desktop is deliberately narrowed to `open_application`/`open_url`/`open_file` for v1 (ADR-15). This is a documented, justified scope reduction, not a silent omission - the brief's concrete examples don't need full GUI automation, and it's the single highest-risk surface in the design.

**Real tensions found in the design and how they were resolved:**

1. **"Retrieval separated from relational data" vs. one SQLite engine for everything.** These look contradictory but aren't once "separated" is defined correctly: the brief's instruction is aimed at Khoj's failure mode (undifferentiated JSON blobs), not at mandating a separate physical server. Resolution: separation is enforced *logically* - distinct tables, distinct repository/service boundaries (`RetrievalService` vs `TaskService` vs `ConversationService`) - while staying in one physical engine for zero-ops simplicity, with a documented, named escape hatch (LanceDB/Qdrant-embedded) if physical separation is ever warranted by scale.

2. **First-run-per-MCP-server confirmation (§4.6) vs. the static-risk-floor/self-report-escalation gate (§4.4).** These are not two competing confirmation systems. First-run-per-server is a one-time trust-establishment gate independent of per-call risk; once a server is trusted, its individual tool calls fall under the normal risk-floor + self-report-escalation flow like any other tool.

3. **Sequential-by-default tool execution (§4.3/ADR-16) vs. background sync workers writing to `calendar_events` concurrently with an in-flight conversation turn (§4.9).** A real potential race. Resolved via SQLite WAL mode (already specified in §4.7), which gives readers a consistent snapshot during a writer's transaction, combined with sync workers using small per-item transactions rather than one long transaction for a whole sync - minimizing any write-lock contention window a concurrent `find_free_slot` read could hit.

4. **Documents-on-filesystem-as-source-of-truth (§4.7) vs. `edit_file`/`write_file` tools (§4.4) potentially mutating an indexed file mid-conversation.** Not a structural contradiction, but it does mean indexing can't be purely on-demand-at-startup; resolved as an implementation note: the indexing pipeline should be triggered by a filesystem watcher (or explicit re-scan) so content-hash incremental re-indexing (§4.8) stays consistent with tool-driven edits, not just external ones.

5. **Local-first-by-default posture (ADR-13) vs. reliable agent-loop tool-calling, where small local models are typically worse at structured tool calling than frontier cloud models.** A genuine tension between the privacy-first product stance and first-run capability. Resolved by narrowing ADR-13's scope: "local-first" governs *data-handling-heavy* defaults (embeddings, memory extraction) strongly, but for the *main conversational/tool-calling* model, first-run setup explicitly detects whether a tool-calling-capable local model is available and prompts the user to pull one or configure a cloud key rather than silently defaulting to a possibly-incapable local model and producing poor agent behavior.

No unresolved contradictions remain; all five are addressed above rather than left implicit.

---

## 5. Next Steps (as of this capture)

This raw dump exists so a future session/agent can pick up without re-running the Explore/Plan agents above. The active plan for turning this into the actual `docs/research/*`, `docs/architecture/*`, `docs/architecture/decisions/*`, and `docs/roadmap/implementation-plan.md` files (per the original task brief's required structure) lives in the Claude Code plan file for this session: `/home/wayne/.claude/plans/khoj-paths-home-wayne-documents-github-k-cosmic-zephyr.md`. That plan should be treated as the source of truth for which files to write and what goes in each; this file is the raw material, not the deliverable structure itself.

Stack decision to carry forward: **Python + React**, superseding any Bun/TS/Tauri-first mentions inherited from Pipali-influenced defaults in the design section above.
