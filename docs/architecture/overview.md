# PSOK Architecture Overview

PSOK is a personal operating system: one AI-powered interface connecting the user's applications, information, tasks, calendar, models, and tools. It is a **single-user, local-first** system — one person, one machine, no tenancy, no operations team. Almost every architectural decision in this document follows from that sentence.

The technology stack is **Python (FastAPI) on the backend and React on the frontend**, with all persistent state in embedded SQLite, the user's documents on the local filesystem, and all secrets in the operating system's keychain.

## The corrected layer model

The project brief sketched a layer diagram as a starting point and explicitly invited correction. Three corrections were necessary, and they change the shape of the system.

**First: the agent loop is a hub, not a stage.** Drawing Interface → AI Runtime → Agents → Tools as a pipeline suggests the runtime happens before the loop and tools happen after it. In reality the loop calls the AI runtime, the tool registry, and the retrieval service as *services*, repeatedly, in a cycle. It is the centre of the diagram, not a row in it.

**Second: skills, tools, MCP, and local computer are not four peers.** Skills are not an execution mechanism at all — they are content the model reads *through* the file tool and executes *through* the shell tool. And MCP tools are not siblings of "tools": they are an additional *source* that registers into the same flat tool registry as builtin tools. Above the dispatcher, everything is a tool.

**Third: scheduling is not a terminal stage.** It is a deterministic service the agent reaches through ordinary tool calls, structurally identical to how it reaches the database.

```
┌──────────────────────────────────────────────────────────────────────┐
│  INTERFACE LAYER                                                      │
│  CLI · HTTP + SSE API · (later) React SPA                            │
│  Knows nothing below except the API contract                          │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  AGENT LOOP  ("the Director")                                         │
│  Single owner of the reason → act → observe cycle.                    │
│  Assembles prompt · calls the runtime · dispatches tool calls ·       │
│  observes results · decides to continue or stop · persists trajectory │
└──────┬──────────────────────┬───────────────────────┬────────────────┘
       │ calls                │ calls                 │ calls
       ▼                      ▼                       ▼
┌──────────────┐   ┌────────────────────────┐   ┌──────────────────┐
│  AI RUNTIME  │   │  TOOL REGISTRY         │   │  RETRIEVAL       │
│              │   │  + DISPATCHER          │   │                  │
│  adapters:   │   │                        │   │  hybrid search   │
│  openai-compat│  │  one flat namespace    │   │  over the vault: │
│  anthropic   │   │  one JSON-Schema shape │   │  sqlite-vec      │
│  google      │   │  permission gate on    │   │  + FTS5, fused   │
│  ollama      │   │  every dispatch        │   │  by rank         │
└──────────────┘   └───────────┬────────────┘   └──────────────────┘
       ▲                       │ tools registered from two sources ↓
       │ read via     ┌────────┴──────────────────┐
       │ view_file    ▼                           ▼
┌──────┴───────┐  ┌─────────────────┐   ┌─────────────────────┐
│   SKILLS     │  │ LOCAL COMPUTER  │   │  MCP CLIENT         │
│              │  │                 │   │                     │
│ SKILL.md     │  │ filesystem      │   │ stdio · SSE ·       │
│ directories  │  │ shell           │   │ streamable-http     │
│              │  │ desktop launch  │   │ OAuth 2.1 + PKCE    │
│ NOT a        │  │ tasks/calendar  │   │                     │
│ separate     │  │ (sandbox +      │   │ external server     │
│ execution    │  │  confirmation)  │   │ processes           │
│ path         │  └────────┬────────┘   └─────────────────────┘
└──────────────┘           │
                           ▼
        ┌────────────────────────────────────────────────┐
        │  SCHEDULING ENGINE (deterministic)              │
        │  date resolution · conflict detection ·         │
        │  free-slot search                               │
        │  reached only through create_task / find_slot   │
        └────────────────────┬───────────────────────────┘
                             ▼
        ┌────────────────────────────────────────────────┐
        │  DATA LAYER — three mechanisms, deliberately    │
        │                                                 │
        │  SQLite (WAL) + sqlite-vec + FTS5               │
        │    app state · tasks · calendar · conversations │
        │    document index · chunks + embeddings ·       │
        │    capability state · audit log                 │
        │                                                 │
        │  Local filesystem                               │
        │    the user's actual documents (source of truth)│
        │                                                 │
        │  OS keychain                                    │
        │    every secret, without exception              │
        └────────────────────────────────────────────────┘
```

## How a request travels

Take *"Find where I wrote about the deploy error, and block an hour tomorrow to fix it."*

1. **Interface** sends the message. It knows nothing about models, tools, or storage.
2. **Agent loop** assembles the prompt: persona, the catalogue of *enabled* skills (names and descriptions only), the tool catalogue, and token-budgeted history. It resolves the conversation's configured provider and calls the **AI runtime**.
3. The model emits `search_documents`. The loop hands it to the **dispatcher**, which checks the permission gate — reading indexed notes carries a low risk floor and passes without a prompt — and routes it to **retrieval**, which fuses vector and keyword results.
4. The result is normalized into the standard envelope, truncated if oversized, appended to the trajectory, and written to the **audit log**. The loop calls the model again.
5. The model emits `find_free_slot`, then `create_task`. Both reach the **scheduling engine**, which resolves "tomorrow" against the system clock and timezone deterministically — never by asking the model to do arithmetic — checks the calendar for conflicts, and writes a task row.
6. `create_task` carries a medium risk floor, so the dispatcher **pauses the loop** and asks the user to confirm through the same transport-agnostic confirmation service that gates shell commands.
7. On approval the write completes; the loop observes the result, emits a plain-text answer, and stops. The full trajectory is persisted.

Every arrow in that walkthrough is a component boundary that exists in the diagram. Nothing special-cases retrieval, scheduling, or confirmation into the loop.

## Design principles

**One component owns the loop.** Prompt assembly, model invocation, dispatch, and termination live together in the Director. There is exactly one place to look when the agent misbehaves.

**Above the dispatcher, everything is a tool.** A builtin function and a JSON-RPC call to an external MCP process are indistinguishable to the model and to the loop. The differences live in how each tool's implementation is constructed, and nowhere else. This is what lets PSOK add capability without touching the core.

**Provider differences never escape their adapter.** The loop deals in one tool representation and one parameter surface. That Gemini rejects schema unions, that some OpenAI models reject reasoning alongside tools, that Anthropic wants an explicit thinking budget — each of these is one module's private problem.

**Skills are content, not code.** Adding a skill means adding a markdown file. There is no registration, no invoke-skill tool, no plugin lifecycle.

**Interpretation is the model's job; computation is not.** The model extracts intent, entities, and constraints from natural language. Deterministic engines do date arithmetic, conflict detection, search ranking, and anything else where being approximately right is the same as being wrong.

**Permission is a floor the model can raise but never lower.** Every tool carries a statically declared risk level. A model's self-assessment of an opaque operation — an arbitrary shell string, a call into an unknown MCP server — can only escalate the requirement.

**Errors are data.** Tool failures become descriptive strings the model reads and reacts to. A failed tool call never ends a run.

**Secrets never touch the model, the database, or the logs.** Credentials live in the keychain, are resolved inside tool implementations at call time, and are redacted from the audit trail.

**Build nothing PSOK does not need yet.** No message broker, no vector service, no container orchestration, no multi-tenancy, no distributed coordination. Every such omission is a decision recorded in an ADR, with a named escape hatch if scale ever changes the answer.

## What each layer owns

| Layer | Owns | Explicitly does not own |
|---|---|---|
| Interface | Rendering, input, streaming display, confirmation prompts | Any knowledge of providers, tools, or storage |
| Agent loop | The reason/act/observe cycle, prompt assembly, termination, trajectory persistence | How any individual tool works; which provider is in use beyond a name |
| AI runtime | Provider adapters, credential resolution, parameter and schema translation, capability declaration | Tool semantics; conversation state |
| Tool registry & dispatcher | The flat namespace, schema exposure, the permission gate, result normalization, audit logging | What any tool does internally |
| Local computer | Filesystem, shell, limited desktop launches, sandboxing | Anything network-facing |
| MCP client | Transports, connection lifecycle, discovery, namespacing, circuit breaking | What external servers do |
| Scheduling engine | Date resolution, conflict detection, free-slot search | Deciding what the user wants |
| Retrieval | Chunking, embedding, hybrid search, context budgeting | Where documents come from |
| Data layer | Persistence, migrations, transactional integrity | Business rules |

## Reading order

- [components.md](components.md) — precise definitions of Tool, Skill, MCP Tool, and Agent, and the rule for choosing between them
- [ai-runtime.md](ai-runtime.md) — the provider abstraction and the agent loop
- [providers.md](providers.md) — the provider catalogue, the failure taxonomy and the fallback chain
- [connectors.md](connectors.md) — connector setup: what is offered, what is said, and what state it is in
- [modes.md](modes.md) — chat and plan modes, status frames, and the turn-cost line
- [data-model.md](data-model.md) — what is stored where, and why three mechanisms
- [security.md](security.md) — the permission model, sandboxing, and credential isolation
- [skills.md](skills.md), [mcp.md](mcp.md), [mcp-oauth.md](mcp-oauth.md), [scheduling.md](scheduling.md) — subsystem detail
- [decisions/](decisions/) — ADRs recording the significant choices and their alternatives
- [../roadmap/implementation-plan.md](../roadmap/implementation-plan.md) — the build order from an empty repository
