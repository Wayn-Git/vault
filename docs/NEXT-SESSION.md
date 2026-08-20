# Backend contract for the PSOK web interface

The frontend is being built against this API. The backend surface is complete,
tested, and now hardened for a browser client; this document is the contract it
exposes. Read `docs/architecture/overview.md` for the system it sits on top of,
and `docs/architecture/ai-runtime.md#what-the-loop-emits` for the event contract
in its permanent home.

**Definition of done for the frontend:** a person can run
`uvicorn psok.api.main:app` plus `npm run dev`, open the browser, and hold a full
conversation — streamed token by token, approving a tool confirmation inline,
switching skills and connectors on and off — without touching the CLI.

## The blocker is gone

**CORS is configured.** The API allows `http://localhost:5173` and
`http://127.0.0.1:5173`. Any other origin needs `PSOK_CORS_ORIGINS` set to a
comma-separated list. It is deliberately not a wildcard: this API runs shell
commands on the machine, so any page the user visits must not be able to drive
it. Verified against a live server with a real `Origin` header, both that the
allowed origin receives `access-control-allow-origin` and that a foreign origin
does not.

## Endpoints

26 endpoints, all verified against a running server.

| Need | Endpoint |
|---|---|
| Conversation list / create | `GET,POST /api/conversations` |
| **Rename, or switch provider/model** | `PATCH /api/conversations/{id}` |
| History | `GET /api/conversations/{id}/messages` |
| **Streamed turn** | `POST /api/conversations/{id}/turn` → SSE |
| **Stop a running turn** | `POST /api/conversations/{id}/turn/stop` |
| **Pending confirmations** | `GET /api/confirmations` |
| **Approve / deny** | `POST /api/confirmations/{request_id}` |
| Skills + connectors with on/off state | `GET /api/capabilities` |
| Toggle one | `POST,DELETE /api/capabilities/{kind}/{name}` |
| `/` autocomplete | `GET /api/skills/search?q=` |
| Every skill, with load errors | `GET /api/skills` |
| Connector catalogue | `GET /api/mcp/catalogue` |
| Configured connectors | `GET /api/mcp/servers` |
| Add / remove a connector | `POST,DELETE /api/mcp/servers` |
| Attach a hand-registered OAuth app | `POST /api/mcp/servers/{name}/oauth-client` |
| Start OAuth, poll for the login URL | `POST /api/mcp/servers/{name}/login`, `GET /api/mcp/authorizations` |
| Connect one now | `POST /api/mcp/servers/{name}/connect` |
| **Remembered facts, and the memory switch** | `GET /api/memory`, `POST /api/memory/toggle`, `DELETE /api/memory/{id}` |
| Audit trail | `GET /api/logs` |
| Component health | `GET /api/health` |

`POST /api/conversations` rejects an unknown provider with a 400, so a bad
provider surfaces as a rejected form rather than a conversation that dies on its
first turn. `PATCH` validates the same way.

`GET /api/health` also returns `provider_defaults`, the model each provider
declares in `providers.yaml`, so an interface can prefill the model rather than
making the user retype what config already says. It reports the **live** registry once a turn has run, including
connected MCP tools, plus `connector_errors` naming any server that failed to
connect. `status` is `degraded` when that map is non-empty.

## Consuming the turn stream

**`EventSource` cannot be used.** The turn endpoint is a `POST` with a JSON body;
the browser's `EventSource` is GET-only. Use `fetch` with a `ReadableStream`
reader and parse `data:` lines, or a library that does the same.

Each frame is `data: {json}` with a `type`:

- `assistant_delta` — `{text}`, append to the visible answer
- `reasoning_delta` — `{text}`, the model's chain of thought; render separately
  or hide, but **never** as the answer
- `assistant_text` — `{text}`, the whole answer at once
- `tool_call` — `{name, arguments}`
- `confirmation_required` — `{request_id, tool_name, operation_key, risk, reason,
  arguments}`, the turn is suspended until this is answered
- `tool_result` — `{name, content, is_error}`
- `warning` — `{message}`, e.g. the stream was cut off
- `guard` — `{reason}`, a loop limit or the user's stop request ended the turn
- `error` — `{message}`, always the last event
- `done` — `{text, iterations}`
- `memory` — `{created, superseded}`, **after** `done`: extraction is a second model
  call, so the turn finishes first and this arrives when something changed

**The answer arrives exactly once.** A streaming provider sends
`assistant_delta` chunks and no `assistant_text`; a non-streaming one sends
`assistant_text` and no deltas. Render whichever arrives. **Do not render
`done.text`** — it repeats the final answer for convenience, and an interface
that shows it as well will show the reply twice.

**Stopping is a request, not an abort.** Aborting the browser's read closes the
response and leaves the loop running — still calling models, still holding a
confirmation open. `POST /api/conversations/{id}/turn/stop` interrupts it: the
in-flight tool call is cancelled and recorded as interrupted, and the stream
ends with a `guard` frame reading `stopped by the user`. Let the stream close
itself rather than aborting the fetch.

**A failed turn is an `error` event, not a dead connection.** Nothing raises out
of the loop any more, so an unconfigured provider or an unreachable model
produces a frame the interface can display. Treat `error`, `guard` and `done` as
terminal and re-enable the composer on all three, and on stream close.

## The confirmation flow, which is the part worth getting right

A medium- or high-risk tool call **suspends the turn**. The stream stays open and
announces it: a **`confirmation_required` frame** arrives after `tool_call`,
carrying `request_id`, `tool_name`, `operation_key`, `risk`, `reason` and
`arguments`. The UI must:

1. Render the prompt from that frame.
2. `POST /api/confirmations/{request_id}` with `{allow, remember}`.
3. The stream then resumes on its own.

`GET /api/confirmations` still lists what is pending, which is what a reloaded
page needs to recover an unanswered prompt. It is the wrong primary mechanism,
though, and the event exists because polling cannot answer either of these:

- **Not every `tool_call` produces a confirmation.** Low-risk tools run without
  one, so a poll started on every `tool_call` never terminates for read-only
  calls.
- **Two pending calls to the same tool are indistinguishable by name.** The
  event carries the request id; the poll response has to be matched by guesswork.

`remember: true` persists a standing approval keyed by `operation_key`, which the
pending-confirmation payload now carries — `run_shell_command:read-only` rather
than `run_shell_command`. That distinction is load-bearing: approving a read-only
shell command must not approve a destructive one. Show the user what they are
about to remember, not just the tool name.

Every MCP server also requires a one-time trust confirmation on first use, so
expect two prompts the first time someone uses a new connector.

## Suggested build order

1. **A hello-world fetch of `/api/health`** in the browser, to confirm the
   origin is allowed.
2. **Conversation view** — create, list, render history.
3. **Streaming** — consume the SSE stream, render `assistant_delta` live. This
   is the core interaction; get it right before anything else.
4. **Confirmation UI** — the flow above. Without it the app hangs on any write,
   so it is not optional polish.
5. **Composer `+` menu** — skills and connectors from `/api/capabilities` with
   toggles. Switching a connector on takes effect on the next turn — the API
   reconciles its live connections at the start of one — so the tiles do not
   need a separate "connect" step. Skills apply immediately.
6. **`/` autocomplete** — backed by `/api/skills/search`. Typing `/name` into the
   message is all the backend needs; it parses and strips the marker itself.
7. **Connector setup** — catalogue, add, OAuth login (render the URL from
   `/api/mcp/authorizations` as a link).
8. **Audit view** — `/api/logs`.
9. **Memory view** — `/api/memory`: what PSOK holds about the user, a switch, and a
   way to forget one fact. The `memory` frame arriving after `done` is the live
   signal that something was learned.

## Ground rules from previous sessions

**Do not ship half-built features.** No reserved enum slots, no schema for
things without code, no docs describing what does not exist. A previous session
left a `PLUGIN` capability kind, four dead tables and three ADRs for unbuilt
features; all were removed. If no code path exercises it, it does not go in.

**Verify the path completes, not that the code is wired.** Three real bugs came
from claiming success after reading the code. The API was reported as serving
MCP tools when no request had ever completed; the confirmation endpoint recorded
decisions without ever waking the waiting turn, because a sync `def` ran it in a
threadpool and `future.set_result()` is not thread-safe; and "don't ask again"
wrote its preference under a key the permission gate never reads back, so the
checkbox did nothing at all. Each was found only by running the actual flow.

**Mutation-check regression tests.** Reintroduce the bug and confirm the test
fails. A test that cannot fail protects nothing.

## Environment facts

- **NVIDIA key is in the OS keychain** at `psok/nvidia`; model
  `nvidia/nemotron-3-ultra-550b-a55b`, embeddings `nvidia/nemotron-3-embed-1b`
  (2048 dims). The key was pasted into a shell and a transcript, so **it is
  worth rotating.** Note that `~/.psok/config/providers.yaml` currently lists
  only `ollama` — the NVIDIA entry has to be added back before that provider
  resolves.
- **No Anthropic or OpenAI key**, so those adapters have only ever run against
  mocks. Their wire-format translation is unverified against the real APIs.
- **Ollama is not running.** It is the *default* embedding provider, so the
  default retrieval path is unexercised. Indexing was verified using NVIDIA
  embeddings instead.
- `sqlite-vec` and FTS5 both work. Bubblewrap is available, so the shell sandbox
  is real and differentially tested.
- Tests: `pytest` (216 unit), `pytest -m live` (5, spawns real MCP servers and
  uses the network). `ruff check psok tests`.

## What exists, verified end to end

Multi-provider runtime with streaming and retry · agent loop with guards ·
18 builtin tools · MCP with OAuth 2.1 + PKCE and a server catalogue ·
permission gate with OS sandboxing · hybrid retrieval over a notes vault ·
long-term memory extracted after a turn and recalled in later conversations ·
markdown skills with `/` invocation · per-conversation capability toggles ·
CLI and HTTP API.

## What is not built

First-party service integrations (Gmail, Calendar and GitHub
are reachable as MCP connectors instead, which may make a separate integration
layer unnecessary — decide based on whether their data needs to be *synced
locally* for cross-referencing). Recurring tasks. Background jobs. Deleting a
conversation: there is no endpoint, because nothing in the architecture docs
calls for one.
