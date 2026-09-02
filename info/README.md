# PSOK — Comprehensive Project Reference

**A personal operating system: one AI agent over your files, shell, tasks, calendar, notes and connected services.**

Single-user and local-first. Your data stays in a SQLite file on your machine, your secrets stay in the OS keychain, and nothing is sent anywhere except to the model provider you choose.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Directory Structure](#directory-structure)
3. [System Components](#system-components)
4. [API Endpoints](#api-endpoints)
5. [Model Providers](#model-providers)
6. [MCP Connectors (Catalogue)](#mcp-connectors-catalogue)
7. [Builtin Tools](#builtin-tools)
8. [Skills System](#skills-system)
9. [Security Model](#security-model)
10. [Data Model & Storage](#data-model--storage)
11. [Configuration System](#configuration-system)
12. [Scheduling & Automation](#scheduling--automation)
13. [Memory & Retrieval](#memory--retrieval)
14. [Frontend](#frontend)
15. [CLI Reference](#cli-reference)
16. [Deployment](#deployment)
17. [Testing](#testing)
18. [Architecture Decision Records (ADRs)](#architecture-decision-records-adrs)
19. [Dependencies](#dependencies)

---

## Architecture Overview

PSOK follows a **single-process architecture** — one uvicorn worker serves both the FastAPI backend and (in production) the built frontend. The system is organized in layers:

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                   │
│              Views: Chat, Tasks, Mail, Memory, etc.          │
├─────────────────────────────────────────────────────────────┤
│                    FastAPI Surface (/api/*)                  │
│           Conversations, Streams, Confirmations, Logs        │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│  Agent   │  Tool    │   MCP    │   Task   │   Capability    │
│ Director │ Registry │ Manager  │ Service  │   Service       │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│              Runtime (Provider Adapters + Fallback)          │
│         OpenAI-compat | Anthropic | Google | Ollama         │
├─────────────────────────────────────────────────────────────┤
│               SQLite + OS Keychain + Filesystem              │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Principles

- **Local-first (ADR-0013):** Embeddings run through Ollama on the user's machine by default. Secrets live in the OS keychain. Documents stay on disk.
- **Single trust boundary (ADR-0007):** The administrator and user are the same person. All MCP servers are fully trusted.
- **Tool indistinguishability (ADR-0005):** Builtin and MCP tools share the same flat namespace and dispatch path. The model cannot tell them apart.
- **Permission gate (ADR-0009):** Every tool declares a static risk floor. The model's self-report can escalate but never lower it. Shell commands run under OS-native sandboxing (Bubblewrap on Linux, Seatbelt on macOS).
- **Errors are data (ADR-0016):** Tool failures come back as structured results, never exceptions.

---

## Directory Structure

```
pkos/
├── backend/                    # Python backend (FastAPI)
│   ├── api/
│   │   └── main.py            # FastAPI app, all 75 route handlers
│   ├── agent/
│   │   ├── director.py        # Reason→act→observe loop (ADR-0016)
│   │   ├── escalation.py      # Tier escalation (heavy model fallback)
│   │   ├── planning.py        # Plan mode (submit_plan, execute_plan)
│   │   └── prompt.py          # System prompt builder, token estimation
│   ├── db/
│   │   ├── connection.py      # SQLite connection management
│   │   ├── repositories.py    # All data access classes
│   │   └── schema.sql         # Database schema
│   ├── mail/
│   │   └── gmail.py           # Gmail read/write via Google connector credentials
│   ├── mcp/
│   │   ├── catalogue.py       # Curated MCP servers (16 entries)
│   │   ├── client.py          # One connection to one MCP server
│   │   ├── commands.py        # CLI actions for MCP (reused by API)
│   │   ├── config.py          # mcp.yaml loading, ServerConfig
│   │   ├── guidance.py        # What the model is told when tools are unavailable
│   │   ├── lifecycle.py       # Connector state machine (off→ready→failed)
│   │   ├── live.py            # Live MCP manager singleton
│   │   ├── manager.py         # MCP lifecycle + tool registration
│   │   ├── migrations.py      # Schema migrations
│   │   ├── oauth.py           # OAuth 2.1 for remote MCP servers
│   │   ├── risk.py            # MCP tool risk classification
│   │   └── ssrf.py            # URL safety checks for remote transports
│   ├── memory/
│   │   ├── service.py         # Long-term memory extraction + recall
│   │   └── store.py           # Memory store (SQLite-backed)
│   ├── retrieval/
│   │   ├── chunking.py        # Markdown chunking + content hashing
│   │   ├── embeddings.py      # Embedding generation (Ollama local default)
│   │   ├── indexer.py         # Content-hash incremental indexing
│   │   ├── search.py          # Hybrid vector + keyword search (RRF fusion)
│   │   └── store.py           # Vector storage (sqlite-vec)
│   ├── runtime/
│   │   ├── availability.py    # Provider reachability checks
│   │   ├── chain.py           # Provider fallback chain
│   │   ├── failures.py        # Retry + fallback decision logic
│   │   ├── http.py            # Shared HTTP client, retry helpers
│   │   ├── registry.py        # Provider registry + resolution
│   │   ├── types.py           # Provider-agnostic types (ToolCall, ModelResponse, etc.)
│   │   └── providers/
│   │       ├── anthropic.py   # Anthropic adapter
│   │       ├── google.py      # Google Gemini adapter
│   │       ├── ollama.py      # Ollama adapter
│   │       └── openai_compat.py # OpenAI-compatible adapter (catches all others)
│   ├── scheduling/
│   │   └── engine.py          # Deterministic date resolution + conflict detection
│   ├── security/
│   │   ├── confirmation.py    # Permission gate (ADR-0009)
│   │   └── sandbox.py         # OS-native shell sandboxing (Bubblewrap/Seatbelt)
│   ├── skills/
│   │   ├── builtin/           # Built-in skills (e.g. psok-intro)
│   │   ├── catalogue.py       # GitHub-hosted skill directory
│   │   ├── install.py         # Skill installation from URL
│   │   └── loader.py          # Skill discovery + SKILL.md parsing
│   ├── sync/
│   │   └── microsoft_todo.py  # Bidirectional Microsoft To Do sync
│   ├── tasks/
│   │   └── service.py         # Task CRUD + calendar operations
│   ├── tools/
│   │   ├── base.py            # Tool, ToolResult, ToolContext, RiskLevel
│   │   ├── registry.py        # Flat tool registry + dispatch + audit
│   │   └── builtin/
│   │       ├── convert.py     # File format conversion (ffmpeg, pandoc, ImageMagick)
│   │       ├── desktop.py     # OS default-handler launches
│   │       ├── documents.py   # Document search + index status
│   │       ├── filesystem.py  # File read/write/edit/delete/list/grep
│   │       ├── shell.py       # Shell execution (sandbox + direct modes)
│   │       ├── tasks.py       # Task + calendar tools
│   │       └── web.py         # Web search (DuckDuckGo) + URL fetch
│   ├── automation.py          # Scheduled turn runner (beta)
│   ├── capabilities.py        # Skills + connectors toggle (global/conversation)
│   ├── cli.py                 # CLI entry point (psok command)
│   ├── config.py              # Paths, providers.yaml, mcp.yaml loading
│   ├── notify.py              # Desktop notifications (osascript/notify-send)
│   ├── provider_catalogue.py  # 18 provider presets with metadata
│   ├── reminders.py           # Due-date reminder loop
│   └── secrets.py             # OS keychain credential resolution
├── frontend/                   # React + Vite frontend
│   ├── src/
│   │   ├── api.js             # API client
│   │   ├── store.jsx          # Global state
│   │   ├── App.jsx            # Router + layout
│   │   ├── views/             # Chat, Dashboard, Mail, Memory, Tasks, Logs, Automations, Capabilities
│   │   ├── components/        # Sidebar, Settings, CommandPalette, ToolCallCard, etc.
│   │   └── hooks/             # useFocusTrap, useMediaQuery, useDismiss
│   └── dist/                  # Built frontend
├── skills/                     # User-installed skills (SKILL.md files)
├── tests/                      # 22 test files + conftest
├── docs/
│   ├── architecture/           # 16 architecture docs
│   ├── decisions/              # 15 ADRs (0001–0017, 0008/0014 absent)
│   ├── images/                 # Interface screenshots
│   └── roadmap/                # Ideas + implementation plans
├── LibreChat/                  # Legacy/reference data
├── pyproject.toml              # Python project config (hatchling build)
├── render.yaml                 # Render deployment (backend)
├── vercel.json                 # Vercel deployment (frontend)
├── README.md                   # User-facing README
└── test.py                     # Standalone test script
```

---

## System Components

### Agent Director (`backend/agent/director.py`)

The single owner of the reason → act → observe cycle. Nothing else decides what happens next.

- **Guards:** max_iterations (12), max_tool_calls (40), max_seconds (600), max_repeated_calls (3), max_continuations (2)
- **Streaming:** responses stream token-by-token to the interface
- **Retry:** transient provider failures trigger retry; the loop continues on empty/truncated replies
- **Escalation:** can escalate to a heavier model tier via `escalate_to_heavy_model` tool
- **Plan mode:** `submit_plan` → `execute_plan` two-phase workflow

### Runtime Layer (`backend/runtime/`)

Provider-agnostic abstraction over LLM APIs:

| Component | Purpose |
|-----------|---------|
| `types.py` | `ToolCall`, `ModelResponse`, `ToolSchema`, `Capabilities`, `ModelParameters`, `StreamEvent`, `ChatClient` protocol |
| `registry.py` | Provider resolution: builtin adapters + any OpenAI-compatible endpoint |
| `chain.py` | Fallback chain: conversation fallback → providers.yaml fallback → file order |
| `failures.py` | Retry/fallback decision: which errors are transient vs. permanent |
| `availability.py` | Provider reachability checks (cached) |
| `http.py` | Shared async HTTP client with retry, timeout, ProviderHTTPError |

### Provider Adapters (`backend/runtime/providers/`)

| Adapter | Protocol | Notes |
|---------|----------|-------|
| `openai_compat.py` | Chat Completions (OpenAI) | Catch-all for any OpenAI-compatible endpoint |
| `anthropic.py` | Messages API (Anthropic) | Native adapter, different request/response format |
| `google.py` | Gemini API (Google) | Native adapter, no streaming yet |
| `ollama.py` | Ollama `/v1` | Local-only, no key required |

### Permission Gate (`backend/security/confirmation.py`)

Every tool call passes through:

1. **Static risk floor** — declared per-tool, model cannot lower it
2. **Sensitive path check** — `~/.ssh`, `~/.aws`, `~/.gnupg`, etc. always confirm
3. **Stored preferences** — "don't ask again" per operation_key
4. **Sandbox enforcement** — Bubblewrap (Linux) / Seatbelt (macOS) for shell commands
5. **Plan mode** — mutating tools refused entirely

### MCP Manager (`backend/mcp/manager.py`)

Manages the lifecycle of all MCP server connections:

- Spawns stdio servers as subprocesses (once per process)
- Discovers tools via MCP protocol
- Registers discovered tools into the flat `ToolRegistry`
- Handles OAuth flows for remote servers
- Retry backoff on failures: 60s → 300s → 1800s

---

## API Endpoints

All routes are under the `/api` prefix. The frontend is served from the root.

### System

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/ping` | Health check (returns `{"status": "ok"}`) |
| GET | `/api/health` | Detailed health with provider + MCP status |

### Providers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/providers` | List configured providers + readiness |
| POST | `/api/providers` | Add a provider from the catalogue |
| DELETE | `/api/providers/{name}` | Remove a provider |

### Conversations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/conversations` | List all conversations |
| POST | `/api/conversations` | Create a new conversation |
| PATCH | `/api/conversations/{id}` | Update title, model, fallback |
| DELETE | `/api/conversations` | Clear all conversations |
| DELETE | `/api/conversations/{id}` | Delete one conversation |
| GET | `/api/conversations/{id}/messages` | Get messages for a conversation |
| POST | `/api/conversations/{id}/messages/{mid}/pin` | Pin/unpin a message |
| GET | `/api/conversations/{id}/pins` | Get pinned messages |

### Agent Turn

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/conversations/{id}/turn` | Execute a streaming agent turn |
| POST | `/api/conversations/{id}/turn/stop` | Interrupt a running turn |

### Confirmations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/confirmations` | List pending confirmation requests |
| GET | `/api/confirmations/preferences` | List stored "don't ask again" preferences |
| DELETE | `/api/confirmations/preferences/{key}` | Remove a stored preference |
| POST | `/api/confirmations/{request_id}` | Approve or deny a confirmation |

### Automations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/automations` | List all automations |
| POST | `/api/automations` | Create an automation |
| PATCH | `/api/automations/{id}` | Update an automation |
| DELETE | `/api/automations/{id}` | Delete an automation |
| POST | `/api/automations/{id}/run` | Trigger an immediate run |
| GET | `/api/automations/{id}/runs` | Get run history |

### Audit Log

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/logs` | Tool execution audit trail |

### MCP Servers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/mcp/catalogue` | Browse installable MCP servers |
| GET | `/api/mcp/servers` | List configured servers + state |
| POST | `/api/mcp/servers` | Add a server (from catalogue or custom) |
| DELETE | `/api/mcp/servers/{name}` | Remove a server + forget credentials |
| POST | `/api/mcp/servers/{name}/oauth-client` | Set OAuth client credentials |
| POST | `/api/mcp/servers/{name}/env` | Set an environment variable |
| DELETE | `/api/mcp/servers/{name}/env/{key}` | Remove an environment variable |
| POST | `/api/mcp/servers/{name}/login` | Start OAuth sign-in flow |
| DELETE | `/api/mcp/servers/{name}/login` | Sign out (forget tokens) |
| POST | `/api/mcp/servers/{name}/logout` | Sign out (alternative) |
| POST | `/api/mcp/servers/{name}/connect` | Connect and register tools |
| POST | `/api/mcp/reconcile` | Reconnect all servers |
| GET | `/api/mcp/authorizations` | List OAuth authorizations |

### Capabilities

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/capabilities` | Overview: skills + connectors with toggle state |
| GET | `/api/capabilities/profiles` | List saved connector profiles |
| POST | `/api/capabilities/profiles` | Save current state as a profile |
| POST | `/api/capabilities/profiles/{name}/apply` | Apply a saved profile |
| DELETE | `/api/capabilities/profiles/{name}` | Delete a profile |
| POST | `/api/capabilities/{kind}/{name}` | Toggle a skill or connector on/off |
| DELETE | `/api/capabilities/{kind}/{name}` | Reset to default |

### Skills

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/skills` | List installed skills |
| GET | `/api/skills/search` | Search the remote skill catalogue |
| GET | `/api/skills/catalogue` | Browse installable skills |
| POST | `/api/skills/install` | Install a skill from a URL |
| POST | `/api/skills/create` | Create a custom skill |
| DELETE | `/api/skills/{name}` | Remove a skill |

### Tools

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tools` | List all available tools (builtin + MCP) |

### Attachments

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/attachments` | Upload a file attachment (max 32MB) |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks` | List tasks |
| POST | `/api/tasks` | Create a task |
| PATCH | `/api/tasks/{id}` | Update a task |
| DELETE | `/api/tasks/{id}` | Delete a task |
| GET | `/api/tasks/buckets` | Get task buckets (My Day, Missed, Important) |
| POST | `/api/tasks/sync` | Trigger Microsoft To Do sync |
| GET | `/api/task-lists` | List task lists |
| POST | `/api/task-lists` | Create a task list |
| PATCH | `/api/task-lists/{id}` | Update a task list |

### Mail (Gmail)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/mail/account` | Get signed-in Gmail account |
| GET | `/api/mail/threads` | List mail threads |
| GET | `/api/mail/threads/{id}` | Get a thread |
| POST | `/api/mail/threads/{id}/reply` | Reply to a thread |
| POST | `/api/mail/messages/{id}/labels` | Add/remove labels |
| GET | `/api/mail/labels` | List labels |

### Calendar (Google Calendar)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/calendar` | List upcoming events |

### Memory

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/memory` | List stored memories |
| POST | `/api/memory/toggle` | Enable/disable memory extraction |
| DELETE | `/api/memory` | Clear all memories |
| DELETE | `/api/memory/{id}` | Delete one memory |

### Frontend Catch-All

| Method | Path | Description |
|--------|------|-------------|
| GET | `/{path}` | Serves built frontend (SPA fallback) |

---

## Model Providers

PSOK ships with 18 provider presets. Any provider name not in the builtin registry resolves to the OpenAI-compatible adapter — so vLLM, LM Studio, or any Chat Completions-compatible endpoint works with no code change.

### Builtin Provider Adapters

| Provider | Adapter | Default Model | Context Window | Notes |
|----------|---------|---------------|----------------|-------|
| Ollama | `ollama` | qwen2.5:7b | — | Local only, no key |
| OpenAI | `openai` | gpt-4o | 128K | |
| Anthropic | `anthropic` | claude-sonnet-4-20250514 | 200K | Native adapter |
| Google Gemini | `google` | gemini-2.0-flash | 1M | Native adapter, no streaming yet |

### Catalogue Presets (API-key providers)

| Slug | Label | Default Model | Notes |
|------|-------|---------------|-------|
| groq | Groq | llama-3.3-70b-versatile | Free tier, fast. max_tools=128, TPM=8000 |
| cerebras | Cerebras | llama-3.3-70b | Free tier |
| openrouter | OpenRouter | — | One key for many providers |
| xai | xAI | grok-2-latest | |
| deepseek | DeepSeek | deepseek-chat | |
| mistral | Mistral | mistral-large-latest | |
| together | Together AI | — | |
| fireworks | Fireworks AI | — | |
| nvidia | NVIDIA NIM | — | Namespaced model IDs |
| modelscope | ModelScope | deepseek-ai/DeepSeek-V4-Flash-0731 | Alibaba, 50 free models |
| ovhcloud | OVHcloud | gpt-oss-120b | EU-hosted, 24 free models |
| llm7 | LLM7 | deepseek-v4-flash | 44 models, free relay |
| ollama-cloud | Ollama Cloud | gpt-oss:120b | Hosted side of local runner |
| cloudflare | Cloudflare Workers AI | @cf/meta/llama-3.3-70b-instruct-fp8-fast | Requires ACCOUNT_ID in URL |

### Provider Configuration

Providers are configured in `~/.psok/config/providers.yaml`. API keys are stored in the OS keychain (or `PSOK_SECRETS_FILE` in containers). Environment variable fallbacks are supported via the `api_key_env` field.

### Provider Fallback

When the chosen provider fails, PSOK falls back through a chain:
1. Conversation-level `fallback` list
2. Global `fallback` key in providers.yaml
3. providers.yaml file order

Max 2 fallback links. Retry budget is shared across the chain.

---

## MCP Connectors (Catalogue)

PSOK ships 16 curated MCP server entries in `backend/mcp/catalogue.py`. Each entry is a template — adding one writes an ordinary `mcp.yaml` entry.

### Auth Types

| Kind | Description |
|------|-------------|
| `none` | Works immediately, no credentials |
| `oauth` | Browser-based OAuth flow (PSOK handles redirect) |
| `setup` | Needs credentials or configuration from the user |

### Connector List

| ID | Title | Category | Auth | Transport | Description |
|----|-------|----------|------|-----------|-------------|
| playwright | Browser (Playwright) | Browser | none | stdio | Navigate, click, fill forms, screenshots |
| chrome-devtools | Browser (Chrome DevTools) | Browser | none | stdio | Chrome DevTools protocol, perf traces |
| github | GitHub | Development | oauth | streamable-http | Repos, issues, PRs, code search, actions |
| google-workspace | Google Workspace | Productivity | setup | stdio | Gmail, Calendar, Drive, Docs, Sheets merged |
| gmail | Gmail | Communication | setup | stdio | Per-service Google connector |
| calendar | Google Calendar | Productivity | setup | stdio | Per-service Google connector |
| drive | Google Drive | Productivity | setup | stdio | Per-service Google connector |
| docs | Google Docs | Productivity | setup | stdio | Per-service Google connector |
| sheets | Google Sheets | Productivity | setup | stdio | Per-service Google connector |
| slides | Google Slides | Creativity | setup | stdio | Per-service Google connector |
| forms | Google Forms | Productivity | setup | stdio | Per-service Google connector |
| tasks | Google Tasks | Productivity | setup | stdio | Per-service Google connector |
| chat | Google Chat | Communication | setup | stdio | Per-service Google connector |
| fetch | Web Fetch | Web | none | stdio | URL to markdown conversion |
| memory | Knowledge Graph Memory | Knowledge | none | stdio | Persistent entity-relation graph |
| vercel | Vercel | Development | oauth | streamable-http | Projects, deployments, logs, docs |
| microsoft-todo | Microsoft To Do | Productivity | setup | stdio | Task lists, tasks, checklists |
| linkedin | LinkedIn | Communication | setup | stdio | Profiles, companies, jobs, feed |
| spotify | Spotify | Media | setup | stdio | Search, playback, playlists |
| tavily | Tavily | Web | setup | streamable-http | Web search tuned for LLMs |
| exa | Exa | Web | setup | streamable-http | Semantic search by meaning |
| firecrawl | Firecrawl | Web | setup | streamable-http | Webpage to clean markdown |

### Google Apps Special Handling

Google's 9 services share one OAuth account. The merged `google-workspace` entry runs one process with `--tools gmail calendar drive docs sheets`. Signing into any Google connector signs into all.

**Google Testing Grant:** Google expires test user consent after 7 days. PSOK surfaces this via `grant_lifetime_days` and warns before expiry.

---

## Builtin Tools

23 builtin tools across 7 modules. The model sees them in a flat namespace alongside MCP tools.

### Filesystem (`backend/tools/builtin/filesystem.py`)

| Tool | Risk | Description |
|------|------|-------------|
| `view_file` | LOW | Read a file with line numbers, offset/limit support |
| `list_files` | LOW | List directory contents with glob filtering |
| `grep_files` | LOW | Search file contents with regex patterns |
| `write_file` | MEDIUM | Create or overwrite a file |
| `edit_file` | MEDIUM | Make targeted edits (find-and-replace) |
| `delete_file` | HIGH | Remove a file or directory |

### Shell (`backend/tools/builtin/shell.py`)

| Tool | Risk | Description |
|------|------|-------------|
| `run_shell_command` | MEDIUM/HIGH | Execute shell commands. Sandbox mode uses Bubblewrap/Seatbelt; direct mode always confirms. Timeout: 30s default, 120s max. |

### Desktop (`backend/tools/builtin/desktop.py`)

| Tool | Risk | Description |
|------|------|-------------|
| `open_url` | MEDIUM | Open URL in default browser |
| `open_application` | MEDIUM | Open file/application with OS default handler |

### Tasks & Calendar (`backend/tools/builtin/tasks.py`)

| Tool | Risk | Description |
|------|------|-------------|
| `create_task` | MEDIUM | Create a task with due date, priority, list |
| `create_tasks` | MEDIUM | Create multiple tasks in one call |
| `update_task` | MEDIUM | Update task properties |
| `list_task_lists` | LOW | List all task lists |
| `list_upcoming` | LOW | List upcoming tasks/events |
| `list_calendar` | LOW | List calendar events |
| `create_calendar_event` | MEDIUM | Create a calendar event |
| `find_free_slot` | LOW | Find a free time slot |

### Documents (`backend/tools/builtin/documents.py`)

| Tool | Risk | Description |
|------|------|-------------|
| `search_documents` | LOW | Search indexed documents (hybrid vector + keyword) |
| `index_status` | LOW | Show indexing statistics |

### Web (`backend/tools/builtin/web.py`)

| Tool | Risk | Description |
|------|------|-------------|
| `search_web` | LOW | Search via DuckDuckGo (no API key) |
| `fetch_url` | LOW | Fetch URL content as markdown |

### File Conversion (`backend/tools/builtin/convert.py`)

| Tool | Risk | Description |
|------|------|-------------|
| `convert_file` | MEDIUM | Convert between formats using ffmpeg, pandoc, ImageMagick, LibreOffice |

---

## Skills System

Skills are directories containing a `SKILL.md` file with YAML frontmatter. They are prompt text — the model reads them through `view_file` when relevant (progressive disclosure).

### Skill Structure

```yaml
---
name: my-skill
description: What this skill does
version: "1.0"
tags: [web, animation]
---
# Skill body (markdown instructions)
```

### Discovery

- `~/.psok/skills/` — user-installed skills
- `skills/` — project-root skills (bundled)
- `backend/skills/builtin/` — built-in skills

### Installation

```bash
psok skills install <url>      # Install from URL
psok skills                    # List installed
psok skills remove <name>      # Remove
```

Skills can be installed from any URL pointing to a raw `SKILL.md` file. GitHub blob URLs are auto-rewritten to raw URLs.

### Remote Catalogue

The skill catalogue fetches from GitHub (`anthropics/skills` repository), parsed from SKILL.md frontmatter. Cached for 1 hour.

---

## Security Model

### Permission Gate (ADR-0009)

Every tool call passes through the confirmation service:

1. **Static risk floor** per tool (LOW / MEDIUM / HIGH)
2. **Model self-report** can escalate but never lower the risk
3. **Sensitive paths** always confirm: `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config/gh`, `.env`, browser profiles, etc.
4. **Stored preferences** — "don't ask again" keyed by `operation[:subtype]`
5. **Plan mode** — all mutating tools refused

### Shell Sandboxing (ADR-0009)

| Platform | Backend | Config |
|----------|---------|--------|
| Linux | Bubblewrap (`bwrap`) | `~/.psok/config/sandbox.yaml` |
| macOS | Seatbelt (`sandbox-exec`) | `~/.psok/config/sandbox.yaml` |
| Windows | None (direct mode + confirmation) | — |

Sandbox policy controls: denied read paths, allowed write paths, network access.

### SSRF Protection (`backend/mcp/ssrf.py`)

Remote MCP URLs are checked at connection time. Private/loopback/multicast IPs are blocked unless `allow_local` is opted in per server.

### Credential Storage (ADR-0012)

- **OS keychain** (default) — `keyring` library, service name `psok`
- **File fallback** (`PSOK_SECRETS_FILE`) — for containers, 0600 permissions
- Keys are never written to config files, databases, or logs
- Audit log redacts any field matching credential patterns

### MCP Risk Classification (`backend/mcp/risk.py`)

MCP tool risk is determined by:
1. Server-declared `annotations` (`readOnlyHint`, `destructiveHint`)
2. Tool name heuristics (e.g., `delete_*` → HIGH, `list_*` → LOW)
3. Default: MEDIUM if nothing matches

---

## Data Model & Storage

### Storage Split (ADR-0004)

| Data | Where |
|------|-------|
| Conversations, messages, tasks, capabilities, confirmations, logs | SQLite (`~/.psok/psok.db`) |
| Documents (source of truth) | Filesystem |
| Document index + vectors | SQLite + sqlite-vec extension |
| API keys, OAuth tokens | OS keychain (or secrets file) |
| MCP server config | `~/.psok/config/mcp.yaml` |
| Provider config | `~/.psok/config/providers.yaml` |
| Sandbox policy | `~/.psok/config/sandbox.yaml` |
| Skills | `~/.psok/skills/` directory |

### Database Tables

| Table | Purpose |
|-------|---------|
| `app_settings` | Key-value settings |
| `confirmation_preferences` | "Don't ask again" decisions |
| `conversations` | Conversation metadata (provider, model, fallback) |
| `messages` | Normalized per-message rows (ADR-0017) |
| `documents` | Indexed document metadata |
| `document_chunks` | Chunked document content + embeddings |
| `task_lists` | Task lists (local + Microsoft To Do mirror) |
| `tasks` | Tasks with due dates, priorities, sync state |
| `calendar_events` | Calendar events |
| `memories` | Long-term memory facts |
| `execution_log` | Tool call audit trail |
| `mcp_trust` | MCP server trust records |
| `capability_state` | Skill/connector toggle state |
| `capability_profiles` | Saved connector profiles |
| `capability_profile_items` | Profile contents |
| `automations` | Scheduled automation definitions |
| `automation_runs` | Automation run history |

---

## Configuration System

### File Paths

| File | Purpose |
|------|---------|
| `~/.psok/psok.db` | SQLite database |
| `~/.psok/config/providers.yaml` | Model provider configuration |
| `~/.psok/config/mcp.yaml` | MCP server configuration |
| `~/.psok/config/sandbox.yaml` | Shell sandbox policy |
| `~/.psok/skills/` | Installed skills |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `PSOK_HOME` | Override default home directory |
| `PSOK_CORS_ORIGINS` | Comma-separated allowed origins |
| `PSOK_SECRETS_FILE` | File-based credential store (containers) |
| `OPENAI_API_KEY` | OpenAI key (conventional) |
| `ANTHROPIC_API_KEY` | Anthropic key (conventional) |
| `GEMINI_API_KEY` | Google key (conventional) |
| `GROQ_API_KEY` | Groq key (conventional) |
| `PSOK_<SLUG>_API_KEY` | Generic fallback for any provider |

### providers.yaml Structure

```yaml
providers:
  - name: anthropic
    base_url: https://api.anthropic.com/v1
    default_model: claude-sonnet-4-20250514
    context_window: 200000
    api_key_ref: psok/anthropic      # OS keychain reference
    api_key_env: ANTHROPIC_API_KEY    # Env var fallback

  - name: my-vllm
    base_url: http://localhost:8000/v1
    default_model: llama-3.1-8b
    context_window: 32768

fallback:
  - groq
  - cerebras
```

### mcp.yaml Structure

```yaml
mcpServers:
  playwright:
    transport: stdio
    command: npx
    args: ["-y", "@playwright/mcp@latest"]
    enabled: true

  github:
    transport: streamable-http
    url: https://api.githubcopilot.com/mcp/
    oauth: true
    enabled: true
```

Environment variables support `${VAR}` interpolation and `keychain:<ref>` for keychain-resolved secrets.

---

## Scheduling & Automation

### Automations (`backend/automation.py`)

Scheduled turns that run without user interaction (beta).

- **Tick interval:** 30 seconds
- **Min interval:** 5 minutes
- **Max interval:** 30 days
- **Run timeout:** 300 seconds
- **Max iterations:** 30 (higher than interactive default)
- **Permission:** denies everything not pre-approved by a standing preference

### Reminders (`backend/reminders.py`)

Due-date reminders fired by the same tick loop:

- Tick every 30 seconds
- Late threshold: 5 minutes past due
- Announced exactly once (conditional update on `reminded_at`)
- Delivered while PSOK is open; late reminders delivered on next start

### Scheduling Engine (`backend/scheduling/engine.py`)

Deterministic date resolution — the model interprets, this module computes:

- `resolve_date_hint("tomorrow at 3pm")` → concrete datetime
- `find_conflicts(start, end)` → overlapping events
- `find_free_slot(duration, after)` → next available slot
- `AmbiguousDate` raised when a hint cannot resolve to one time (model decides)

---

## Memory & Retrieval

### Long-Term Memory (`backend/memory/`)

Two-tier design (from Khoj research):

1. **Tier 1:** Verbatim transcript (message table)
2. **Tier 2:** Curated standing facts (memory store)

After each turn, the model extracts durable facts via a structured create/supersede diff. Most turns produce no changes. Facts are offered to the system prompt (max 30, recency + semantic search).

### Document Retrieval (`backend/retrieval/`)

| Component | Purpose |
|-----------|---------|
| `indexer.py` | Content-hash incremental indexing (only changed chunks re-embedded) |
| `chunking.py` | Markdown-aware chunking with heading paths |
| `embeddings.py` | Local default (Ollama nomic-embed-text), cloud configurable |
| `search.py` | Hybrid vector + keyword search fused by reciprocal rank |
| `store.py` | Vector storage via sqlite-vec extension |

Indexed content supports: `.md`, `.txt`, `.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, `.c`, `.json`, `.yaml`, `.toml`, `.html`, `.css`, and more.

---

## Frontend

React 19 + Vite 8 single-page application.

### Views

| View | Description |
|------|-------------|
| `Chat.jsx` | Main conversation interface with streaming |
| `Dashboard.jsx` | Overview / landing |
| `Tasks.jsx` | Task management with lists and buckets |
| `Mail.jsx` | Gmail interface |
| `Memory.jsx` | Long-term memory management |
| `Logs.jsx` | Tool execution audit trail |
| `Automations.jsx` | Scheduled automation management |
| `Capabilities.jsx` | Skills + connectors toggles, profiles |

### Key Components

| Component | Description |
|-----------|-------------|
| `Sidebar.jsx` | Navigation + conversation list |
| `Settings.jsx` | Provider, model, configuration |
| `CommandPalette.jsx` | Keyboard-driven command interface |
| `ToolCallCard.jsx` | Tool call display with approval |
| `ModelMenu.jsx` | Model selection |
| `ConfirmModal.jsx` | Permission confirmation dialog |
| `connectorState.js` | Connector state management |
| `markdown/` | Markdown rendering with syntax highlighting |

### Stack

- React 19.2.8
- React Router DOM 7.18
- Phosphor Icons
- Refractor (syntax highlighting)
- Vite 8.2 with React plugin
- oxlint for linting

---

## CLI Reference

```bash
psok init                        # Create ~/.psok, database, default config
psok doctor                      # Report configuration + component status

# Chat
psok chat                        # Interactive chat
psok chat --provider anthropic   # Chat with specific provider
psok chat --workspace ~/notes    # Chat with workspace root

# Providers
psok providers list              # List configured providers
psok providers catalogue         # Show known providers
psok providers add <name>        # Add a provider
psok providers remove <name>     # Remove a provider

# Secrets
psok secrets set <ref>           # Store API key in keychain
psok secrets list                # List stored keys
psok secrets delete <ref>        # Remove a key

# MCP
psok mcp catalogue               # Browse installable servers
psok mcp status                  # Show configured servers
psok mcp add <id>                # Add from catalogue
psok mcp add <name> --command .. # Add custom server
psok mcp remove <name>           # Remove a server
psok mcp login <name>            # Sign in to a server
psok mcp logout <name>           # Sign out
psok mcp connect                 # Connect all servers

# Tasks
psok tasks                       # List tasks
psok task-lists                  # List task lists

# Memory
psok memory                      # List memories

# Skills
psok skills                      # List installed skills
psok skills install <url>        # Install from URL

# Documents
psok index <path>                # Index a folder for retrieval
psok search <query>              # Search indexed documents

# Logs
psok logs                        # Tool execution audit trail

# Capabilities
psok capabilities                # List skills + connectors
psok capabilities toggle <kind> <name>  # Toggle on/off

# Server
psok serve                       # Run API + frontend
psok serve --open                # Open browser on start
```

---

## Deployment

### Render (Backend)

`render.yaml` defines a single web service:

- **Runtime:** Python 3.12
- **Worker:** 1 (single process for MCP subprocesses + state)
- **Disk:** 1GB mounted at `/var/psok` (persists SQLite, config, skills)
- **Health check:** `/api/ping`
- **Build:** `pip install -e ".[providers]"`
- **Start:** `uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT --workers 1`

Required env vars: `PSOK_HOME=/var/psok`, `PSOK_SECRETS_FILE=/var/psok/secrets.json`, `PSOK_CORS_ORIGINS=https://<your-app>.vercel.app`

### Vercel (Frontend)

`vercel.json` builds and serves the React frontend:

- **Build:** `npm ci && npm run build`
- **Output:** `frontend/dist`
- **SPA rewrite:** all non-asset paths → `index.html`
- **Cache:** assets immutable, `index.html` no-store

Required env var: `VITE_API_BASE=https://<backend-service>.onrender.com`

### Local

```bash
uv venv
uv pip install -e '.[dev]'
psok init
cd frontend && npm install && npm run build
psok serve --open
```

---

## Testing

22 test files in `tests/`:

| Test File | Coverage |
|-----------|----------|
| `test_api_surface.py` | API endpoint contracts |
| `test_runtime_and_agent.py` | Agent loop + runtime |
| `test_providers_and_fallback.py` | Provider resolution + fallback chain |
| `test_tools.py` | Builtin tool dispatch |
| `test_permissions.py` | Permission gate |
| `test_sandbox.py` | Shell sandboxing |
| `test_mcp.py` | MCP client + manager |
| `test_mcp_live.py` | Live MCP server tests (opt-in) |
| `test_memory.py` | Memory extraction + recall |
| `test_retrieval.py` | Document indexing + search |
| `test_scheduling.py` | Date resolution + conflicts |
| `test_tasks.py` | Task CRUD |
| `test_task_lists_and_buckets.py` | Task lists + buckets |
| `test_connectors_and_reminders.py` | Connector state + reminders |
| `test_connector_setup.py` | Connector configuration |
| `test_oauth_flow.py` | OAuth flow |
| `test_mail.py` | Gmail operations |
| `test_convert.py` | File conversion |
| `test_install_and_web.py` | Skill install + web tools |
| `test_modes_and_status.py` | Capability modes |
| `test_capabilities.py` | Capability service |
| `test_stop_and_streaming.py` | Turn stop + streaming |
| `test_regressions.py` | Regression tests |
| `test_api_surface.py` | API surface coverage |

Run: `pytest` (excludes live tests). Run live: `pytest -m live`.

Lint: `ruff check backend tests` (line length 100, Python 3.11+).

---

## Architecture Decision Records (ADRs)

| ADR | Title |
|-----|-------|
| 0001 | AI provider abstraction — adapter per protocol, OpenAI-compatible catch-all |
| 0002 | Primary database engine — SQLite |
| 0003 | Vector storage — sqlite-vec extension |
| 0004 | Storage architecture — multi-store split (SQLite + filesystem + keychain) |
| 0005 | Tool architecture — flat registry, uniform dispatch, risk levels |
| 0010 | Scheduling architecture — deterministic date resolution, model interprets |
| 0011 | Authentication — OAuth 2.1 for remote MCP, OS keychain for secrets |
| 0012 | Credential storage — OS keychain, file fallback for containers |
| 0013 | Local-first AI default posture — embeddings via Ollama, local data |
| 0015 | Desktop GUI automation scope — default-handler launches only, no screenshots |
| 0016 | Agent loop ownership and concurrency — single Director, sequential tool calls |
| 0017 | Conversation message persistence model — normalized per-message rows |

---

## Dependencies

### Python (pyproject.toml)

**Core:**
- `fastapi>=0.115` — API framework
- `uvicorn[standard]>=0.32` — ASGI server
- `pydantic>=2.9` — Data validation
- `httpx>=0.27` — Async HTTP client
- `mcp>=2.0` — Model Context Protocol SDK
- `pyyaml>=6.0` — YAML config parsing
- `keyring>=25.0` — OS keychain access
- `python-dateutil>=2.9` — Date parsing
- `python-multipart>=0.0.9` — File uploads

**Optional:**
- `openai>=1.55` — OpenAI SDK
- `anthropic>=0.40` — Anthropic SDK
- `sqlite-vec>=0.1.6` — Vector search extension

**Dev:**
- `pytest>=8.3` + `pytest-asyncio>=0.24` — Testing
- `ruff>=0.8` — Linting

### JavaScript (package.json)

- `react` 19.2.8 + `react-dom` 19.2.8
- `react-router-dom` 7.18.3
- `@phosphor-icons/react` 2.1.10
- `refractor` 5.0.0 (syntax highlighting)
- `simple-icons` 16.29.0
- `vite` 8.2.0 + `@vitejs/plugin-react` 6.0.4
- `oxlint` 1.75.0 (linting)
- `playwright-core` 1.56.0 (smoke tests)
