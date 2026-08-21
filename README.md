# PSOK

A personal operating system: one AI interface to your files, shell, tasks, calendar, and
connected services. Single-user, local-first — your data stays in a SQLite file on your
machine and your secrets stay in the OS keychain.

## Quick start

```bash
uv venv
uv pip install -e '.[dev]'

psok init      # create ~/.psok, the database, and default config
psok doctor    # report component health
```

Configure a model provider in `~/.psok/config/providers.yaml`. Ollama is preconfigured;
for a cloud provider, store the key in the keychain rather than the file:

```python
from psok.secrets import set_secret
set_secret("psok/anthropic", "sk-ant-...")
```

```yaml
providers:
  - name: anthropic
    api_key_ref: psok/anthropic        # a keychain reference, never a key
    default_model: claude-sonnet-4-20250514
```

Then:

```bash
psok chat --provider anthropic --workspace ~/notes
psok logs                              # every tool call, with the decision that allowed it
```

Or use it in a browser:

```bash
cd frontend && npm install && npm run build   # once
psok serve --open                             # http://127.0.0.1:8000
```

`psok serve` is one process for the whole product: the API under `/api`, the
built interface everywhere else. Working on the interface itself means running
Vite alongside it (`cd frontend && npm run dev`), which proxies `/api` to the
API. Serving the bundle from some other origin means setting `PSOK_CORS_ORIGINS`
to a comma-separated list — deliberately not a wildcard, since this API can run
shell commands on the machine. See [docs/interface.md](docs/interface.md).

Any OpenAI-compatible endpoint — vLLM, LM Studio, NVIDIA NIM, Groq, OpenRouter — works
with a `base_url` entry and no code change.

## Searching your notes

```bash
psok index ~/notes          # chunk, embed and index a folder
psok index --status
psok search "that error code"
```

Indexing is incremental: re-running it on an unchanged vault does no embedding
work, and editing one file re-embeds only the chunks that changed. Search fuses
semantic similarity with a real BM25 keyword index, so both paraphrases and exact
terms like error codes work. Embeddings run locally through Ollama by default.

## What PSOK remembers

```bash
psok memory                 # the standing facts, with the ids to forget them by
psok memory --forget 3      # retire one; the row survives, recall stops
psok memory --off           # globally, or --off --conversation <id> for one
```

Facts are extracted after a turn by a small model and recalled in later conversations.
Name a cheap local model for the job in `providers.yaml`, or let it use the
conversation's own:

```yaml
memory:
  provider: ollama
  model: qwen2.5:3b
```

## Skills

```bash
psok skills                                                  # what is installed
psok skills --install https://github.com/o/r/blob/main/skills/x/SKILL.md
psok skills --remove x
```

A skill is a directory with a SKILL.md (ADR-0006), so installing one is a
download and a validation: the file is staged and parsed before it is placed,
under the name its frontmatter declares, and a download that turns out not to be
a skill leaves nothing behind.

The interface's Directory browses the same thing: skills are read live from
their source repositories — real names and descriptions out of the files
themselves — and install with one click, alongside the MCP catalogue.

## What runs without asking

```bash
psok permissions                                   # every standing "don't ask again"
psok permissions --revoke run_shell_command:read-only
```

Approvals are kept by operation key rather than tool name, so approving a
read-only shell command never approved a destructive one. The Activity view
lists the same grants with a way to take one back.

## Connecting apps over MCP

```bash
psok mcp catalogue          # browse what you can connect
psok mcp add playwright     # browser control, works immediately
psok mcp add github         # prints the one-time OAuth setup steps
psok mcp login github       # opens GitHub's real login page in your browser
psok mcp status
```

A server that takes its credentials through the environment keeps them in the
keychain too — `mcp.yaml` stores only the reference:

```bash
psok mcp env google-workspace GOOGLE_OAUTH_CLIENT_ID=1234.apps.googleusercontent.com
psok mcp env google-workspace GOOGLE_OAUTH_CLIENT_SECRET=... --secret
```

Custom servers work the same way:

```bash
psok mcp add my-server --url https://mcp.example.com/mcp --oauth
psok mcp add local-tool --command npx --args -y some-mcp-server
```

Connected tools join the same flat namespace as builtins, so the model uses them
without knowing they are remote. Tokens go to the OS keychain; `mcp.yaml` holds only
references. See [docs/architecture/mcp-oauth.md](docs/architecture/mcp-oauth.md).

## What works today

Multi-provider AI runtime (OpenAI-compatible, Anthropic, Google, Ollama, and any
OpenAI-compatible endpoint) with runtime model switching and retry on transient
provider failures · the agent loop with iteration, time, and repetition guards ·
streaming responses · 20 builtin tools across filesystem, shell, desktop, tasks,
calendar, document search and the open web · hybrid retrieval over your notes (semantic + BM25,
incremental indexing) · MCP connectivity with OAuth 2.1, PKCE, and a curated server
catalogue · a permission gate with OS-level sandboxing on macOS and Linux ·
deterministic natural-language scheduling · markdown skills · a CLI and an HTTP API.

Long-term memory across conversations: PSOK extracts standing facts after a turn and
recalls them in later ones, with a create/supersede diff rather than an ever-growing
transcript.

Skills, connectors and memory can each be switched on or off, globally or per
conversation, and `/skill-name` engages a skill directly.

A React interface over the same API: a rail of conversations, streamed answers
rendered as markdown, inline permission prompts, a command palette over every
action, a directory for installing skills and adding connectors, file
attachments, and connector setup — catalogue, OAuth, credentials — without
dropping to the CLI. Everything in it is reachable from the keyboard; `?` lists
the bindings.

Not built: first-party service integrations.
Those are described in the [roadmap](docs/roadmap/implementation-plan.md) as future work,
not in the architecture docs as if they exist.

## How it is put together

```
Interface (CLI · HTTP/SSE API · React app served by the same process)
        │
   Agent Loop ── the single owner of reason → act → observe
        ├── AI Runtime ......... provider adapters behind one contract
        ├── Tool Registry ...... one flat namespace; permission gate on every dispatch
        │     ├── builtin ...... filesystem, shell, desktop, tasks, calendar
        │     └── MCP .......... browser, GitHub, Google, or any server you add
        └── Retrieval .......... hybrid search over your notes
                │
        SQLite (+vec, +FTS5) · filesystem for documents · OS keychain for secrets
```

Three ideas carry most of the design:

**Above the dispatcher, everything is a tool.** A builtin function and a JSON-RPC call to
an external MCP process are indistinguishable to the model. New capability does not touch
the core.

**Permission is a floor the model can raise but never lower.** Every tool declares a static
risk level. A model's self-assessment of an opaque operation can only escalate it. Paths
under `~/.ssh`, `~/.aws`, and similar always confirm, and no stored preference can silence
that.

**Interpretation is the model's job; computation is not.** The model extracts *"tomorrow"*;
a deterministic engine resolves it against the clock, checks the calendar, and reports
conflicts back rather than guessing.

## Documentation

- [Architecture overview](docs/architecture/overview.md) — the layer model and a worked request
- [Components](docs/architecture/components.md) — Tool vs Skill vs MCP Tool vs Agent
- [Data model](docs/architecture/data-model.md) · [AI runtime](docs/architecture/ai-runtime.md) · [Security](docs/architecture/security.md)
- [Decision records](docs/architecture/decisions/) — ADRs with alternatives and trade-offs
- [The web interface](docs/interface.md) — how the React app is put together, and every keyboard binding
- [Research](docs/research/) — what was taken from Pipali, Khoj, and LibreChat, and what was rejected

## Development

```bash
pytest              # 256 unit tests
pytest -m live      # 5 more against real MCP servers (spawns processes, uses network)
ruff check psok tests
cd frontend && npm run lint && npm run build
npm run smoke       # drives a real browser against a running psok serve
```

Sandbox containment is tested against the real OS and skips where unavailable
(Windows, or Linux without `bubblewrap`). The live suite exists because a transport
that only works against a mock is not evidence that MCP works.
