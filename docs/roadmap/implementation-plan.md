# Implementation Plan

Build order from an empty repository. The sequence is driven by dependency, not by feature priority: each phase's acceptance criteria are testable using only what earlier phases built.

Stack: Python 3.11+ with FastAPI on the backend, React with Vite on the frontend, SQLite (WAL) for persistence, the OS keychain for secrets.

**Status legend:** ✅ built and tested · ◻ not started

---

## ✅ Phase 0 — Scaffolding

**Goal.** A repository that installs, lints, and runs a test suite.

**Components.** `pyproject.toml` (hatchling, `uv`-managed), package skeleton matching the architecture's component boundaries, pytest with asyncio auto mode, ruff.

**Dependencies.** None.

**Acceptance.** `uv pip install -e '.[dev]'` succeeds; `pytest` and `ruff check` both run clean on an empty suite.

---

## ✅ Phase 1 — Data layer

**Goal.** Every later phase has somewhere to persist state.

**Components.** `psok/db/schema.sql` (all tables from [data-model.md](../architecture/data-model.md)), `psok/db/connection.py` (WAL, foreign keys, busy timeout, short-transaction helper), `psok/db/repositories.py` split by domain, `psok/secrets.py` (keychain wrapper plus audit redaction), `psok/config.py` (paths, `providers.yaml`).

**Dependencies.** Phase 0.

**Tests.** Schema applies idempotently; repository round-trips; redaction covers both credential-shaped key names and value patterns; audit rows store redacted arguments.

**Acceptance.** `psok init` produces a working database; no secret value can reach a table.

---

## ✅ Phase 2 — AI runtime

**Goal.** PSOK can talk to any provider without the rest of the system knowing which.

**Components.** `runtime/types.py` (normalized message, response, tool-schema, capability shapes), `runtime/registry.py` (registry plus OpenAI-compatible fallback), adapters for OpenAI-compatible, Anthropic, Google, and Ollama.

**Dependencies.** Phase 1 (credential resolution).

**Tests.** An unconfigured provider name in `providers.yaml` resolves through the fallback; Gemini schema sanitization flattens unions and stringifies enums; OpenAI drops `reasoning_effort` when tools are present; Anthropic converts tool results to content blocks.

**Acceptance.** Adding a new OpenAI-compatible provider is a config edit with no code change.

---

## ✅ Phase 3 — Agent loop and tool registry

**Goal.** The spine everything else attaches to.

**Components.** `tools/base.py` (tool contract, result envelope, risk levels), `tools/registry.py` (flat namespace, single dispatch path, truncation, audit), `agent/prompt.py` (system prompt, token budgeting), `agent/director.py` (the loop and its guards).

**Dependencies.** Phases 1–2.

**Tests.** Loop terminates on plain text; loop incorporates a tool result and continues; iteration, tool-count, time, and repetition guards each fire; a model error is reported rather than raised; a denied tool result still reaches the model as an observation.

**Acceptance.** A full turn with a tool call runs end to end against a scripted provider with no network.

---

## ✅ Phase 4 — Local computer tools, permissions, sandbox

**Goal.** PSOK can act on the machine safely.

**Components.** `tools/builtin/filesystem.py`, `tools/builtin/shell.py`, `tools/builtin/desktop.py`, `security/confirmation.py` (static risk floor, escalation-only self-report, sensitive-path denylist, persisted skip-keys), `security/sandbox.py` (Seatbelt/Bubblewrap wrapping).

**Dependencies.** Phase 3.

**Tests.** Risk floor cannot be lowered by self-report; a standing preference cannot silence the sensitive-path check; a first MCP-server call establishes trust once; shell captures exit codes and times out cleanly; **the sandbox demonstrably masks a denied credential path while direct mode reads it.**

**Acceptance.** Dangerous operations pause for approval; sandbox containment is verified against the real OS rather than mocked.

---

## ✅ Phase 5 — Skills

**Goal.** Procedures can be added without code.

**Components.** `skills/loader.py` (scan, validate, seed builtins, format the catalogue), one builtin skill.

**Dependencies.** Phases 3–4 (skills execute through the file and shell tools).

**Tests.** Frontmatter validation rejects malformed skills with a reported reason; the catalogue appears in the system prompt while the skill body does not.

**Acceptance.** Dropping a `SKILL.md` into `~/.psok/skills/` makes it usable with no restart.

---

## ✅ Phase 6 — Scheduling engine, tasks, calendar

**Goal.** The brief's worked example runs end to end.

**Components.** `scheduling/engine.py` (deterministic date resolution, conflict detection, greedy free-slot scan), `tools/builtin/tasks.py`.

**Dependencies.** Phases 1, 3, 4.

**Tests.** Relative-date resolution across timezone-sensitive forms; an unresolvable hint raises rather than guessing; a conflict is reported back through the loop instead of silently overwritten; task tools pass through the same permission gate as any other write.

**Acceptance.** *"Finish my ML assignment tomorrow"* produces a correctly dated, persisted, confirmable task.

*Sequenced before retrieval because it depends only on the loop and the permission model, and it lands a headline capability early.*

---

## ✅ Phase 7a — Runtime consistency pass

**Goal.** Remove two cross-cutting inconsistencies before more layers depend on them.

**Components.** `runtime/http.py` — shared retry with exponential backoff and jitter, honouring `Retry-After`, applied to every adapter rather than one; streaming (`stream()`) for the OpenAI-compatible and Anthropic adapters, including reassembly of tool calls whose arguments arrive fragmented across chunks.

**Why here.** Retry lived only in the OpenAI-compatible adapter, leaving Anthropic and Google exposed to exactly the transient 5xx observed against NVIDIA NIM. `Capabilities.streaming` defaulted to `True` while no adapter streamed — a flag the code did not honour. Streaming touches the adapter interface, the loop and the API together, so doing it after a frontend exists would mean changing all three again.

**Tests.** Retry on 5xx and 429; no retry on 4xx; give-up after the cap; deltas assembled into a final response; fragmented tool arguments reassembled; the loop falling back cleanly when a provider cannot stream.

**Acceptance.** Verified live against NVIDIA: first token in 1.4s, reasoning captured separately from the answer, tool calls correctly reassembled. Google now declares `streaming=False` rather than claiming a capability it lacks.

---

## ✅ Phase 7 — Interface surface

**Goal.** Something to drive PSOK with.

**Components.** `psok/cli.py` (`init`, `doctor`, `chat`, `logs`), `psok/api/main.py` (conversations, streaming turns, pending confirmations, audit log, skills).

**Dependencies.** Phases 3–6.

**Acceptance.** `psok doctor` reports component health; the API streams a turn and surfaces confirmations for a UI to answer.

**Hardened for a browser client afterwards.** CORS for the Vite dev origin, without which no frontend request reaches a route at all; failures inside an open SSE stream reported as an `error` event rather than a truncated body; an unknown provider rejected when the conversation is created rather than mid-turn; `PATCH /api/conversations/{id}` so switching model mid-conversation is an action a UI can take; a lock around registry construction so two concurrent turns cannot each build an MCP manager.

---

## ✅ Phase 8 — Retrieval and document indexing

**Goal.** PSOK can answer from the user's own documents.

**Components.** Filesystem walker and watcher; chunking with heading prefixes; content-hash incremental indexing; embeddings via the Phase 2 adapters (local by default); `sqlite-vec` population; FTS5 keyword index; reciprocal-rank fusion; a `search_documents` tool; retrieval injection into prompt assembly.

**Dependencies.** Phases 1–3. Tool-driven file edits must invalidate the index (see [data-model.md](../architecture/data-model.md#filesystem-and-index-consistency)), so this depends on Phase 4 too.

**Tests.** Chunk boundaries and heading paths; editing one file re-embeds only its changed chunks; hybrid search beats vector-only on an exact-term query; budgeted context assembly stays within the model's window.

**Acceptance.** Pointing PSOK at a notes directory makes it queryable; re-scanning an unchanged vault performs no embedding work. Both verified, including semantic hits on queries sharing no words with the source text.

**Built beyond the original plan.** The query embedder is pinned to whichever model built the index — embedding a query with a different model puts it in an unrelated vector space and returns plausible nonsense rather than failing. The model is recorded at index time and adopted automatically at search time.

---

## ✅ Phase 9 — Memory

**Goal.** PSOK remembers across conversations.

**Components.** Post-turn fact extraction returning a create/supersede diff; recency plus semantic recall; `<memories>` injection; per-conversation toggle. `psok memory` and `/api/memory` for listing, forgetting, and switching it off.

**Dependencies.** Phase 8 — deliberately reuses its embedding and vector infrastructure rather than duplicating it.

**Tests.** Diff application creates and supersedes correctly; recall merges and deduplicates the two retrieval paths; the toggle genuinely disables extraction; a malformed or hallucinating extractor costs only that turn; an empty store never reaches the embedder; a failed extraction leaves the finished turn alone.

**Acceptance.** A fact stated in one conversation is recalled unprompted in a later, separate one. Verified through the loop and over HTTP.

**Where extraction sits in the turn.** After the `done` event, not before it. Extraction is a second model call, and blocking the terminal event on it would keep an interface's composer disabled for the length of one. When it changes something, a `memory` event follows with the facts created and retired.

**The extraction model.** `memory:` in `providers.yaml` names a small, cheap, local model for the role ([ADR-0013](../architecture/decisions/0013-local-first-ai-default-posture.md)); with none configured it falls back to the conversation's own model, so memory works on a machine with one provider rather than silently doing nothing.

**Built beyond the original plan.** Exact duplicates are refused at the store rather than only discouraged in the prompt — restating a held fact is the extractor's documented main failure mode, and a prompt is the wrong place to enforce it alone.

---

## ✅ Phase 10 — MCP connectivity

**Goal.** External capability without writing it.

**Components.** `mcp.yaml` loader; stdio, SSE, and streamable-HTTP clients via the Python MCP SDK; SSRF protection at transport construction; composite key namespacing; result normalization into the standard envelope; circuit breaker; registration into the Phase 3 registry.

**Dependencies.** Phases 3–4 (the first-call trust gate already exists in the confirmation service).

**Tests.** Transport connection against a mock server; same-named tools from two servers do not collide; a private-IP URL is refused; the circuit breaker opens after repeated failures. A separate `pytest -m live` suite spawns real MCP servers over the network, because a transport that only works against a mock is not evidence that MCP works.

**Acceptance.** A real third-party MCP server's tools appear alongside builtins, correctly namespaced and normalized. Verified.

**Built beyond the original plan.** OAuth 2.1 with PKCE for servers that require their own login, a curated server catalogue behind `psok mcp add`, and per-conversation connector toggles. See [mcp-oauth.md](../architecture/mcp-oauth.md).

---

## ◻ Phase 11 — Integrations

**Goal.** Gmail, Google Calendar, GitHub.

**Components.** Not designed. Gmail, Calendar and GitHub are currently reachable as MCP connectors, so this phase only becomes worth doing if PSOK needs their data synced into local tables to be cross-referenced. That need has not appeared yet, and the design should follow the need rather than precede it.

**Dependencies.** Everything prior. Highest external-dependency surface — OAuth applications, third-party quotas — so it benefits from every earlier phase being stable.

**Tests.** Mocked OAuth round trip; incremental sync via etag; credential redaction in the audit log; idempotent upserts converge under retry.

**Acceptance.** Gmail search works from the agent; `find_free_slot` reflects real external calendar events; no token appears in the database or logs.

---

## ✅ Phase 12 — React frontend

**Goal.** The interface most use will go through.

**Components.** Vite and React app against the Phase 7 API. Status, chat, MCP, skills, memory and audit views; streamed turns with tool-call cards; an inline confirmation prompt driven by the `confirmation_required` frame; the `+` menu for skills, connectors and memory, scoped globally or to one conversation; `/` skill autocomplete; provider and model switched from the conversation strip; Stop wired to the interrupt endpoint.

**Dependencies.** Phase 7, and ideally 8–11 so there is something to display.

**Acceptance.** A full turn including a confirmation can be driven entirely from the browser. Verified through Vite's proxy against a live API: a tool call suspends, the prompt is answered from the id its frame carried, the turn resumes and answers, the model is switched mid-conversation, and Stop interrupts a suspended call and records it as interrupted.

**Not covered by tests.** The React app has no test suite: `npm run build` and `oxlint` pass, and the flows above were driven against a live server, but nothing locks the components' behaviour down. That is the largest remaining gap in this phase.

---

## ◻ Phase 13 — Stretch

Not designed in detail; each needs its own decision when reached. Desktop wrapper (Tauri or Electron); full GUI automation under [ADR-0015](../architecture/decisions/0015-desktop-gui-automation-scope.md)'s separate risk gate; cross-encoder reranking; constraint-solver auto-scheduling; WhatsApp and Instagram; sub-agent delegation; remote or multi-device access (which reopens [ADR-0011](../architecture/decisions/0011-authentication.md)).
