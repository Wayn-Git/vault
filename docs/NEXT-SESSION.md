# Where PSOK stands, and what the next session should do

**The project continues.** An earlier note in this file framed this as a final
archive; it was premature. Read this one instead — it is a working plan, not a
eulogy. The API contract below is still accurate and still the reference for
the interface; what changed is the closing section, which is now a punch list
instead of a goodbye.

## What exists, verified end to end

Multi-provider AI runtime (NVIDIA NIM live-tested, Ollama configured, OpenAI-
compatible fallback for any endpoint) with streaming and retry · agent loop
with iteration/time/repetition/**continuation** guards, so a turn that comes
back empty or truncated is continued rather than silently ended · 20 builtin
tools across filesystem, shell, desktop, tasks, calendar, document search and
the open web (`search_web`, `fetch_url`) · MCP with OAuth 2.1 + PKCE, a curated
catalogue, SSRF protection, per-server circuit breaking · permission gate with
OS sandboxing (Bubblewrap on this machine) · hybrid retrieval over a notes
vault (BM25 + vector, incremental indexing) · long-term memory extracted after
a turn and recalled in later ones · markdown skills, installable from a URL or
browsed or written from three fields on one Skills & connectors page · a full
React
interface served by the same process as the API (`psok serve`) · standing
permission approvals, listable and revocable, in both the UI and the CLI · a
CLI covering all of the above.

**Verified, not just wired**: 268 unit tests, `ruff` clean, and a 53-check
Playwright suite (`frontend/tests/smoke.mjs`) that drives a real browser
against a real running server and a real model — streaming, markdown rendering
exactly once, the thinking arriving live and folding away when the answer
starts, the permission gate answering to the keyboard, a skill installed from
the catalogue and another written from three fields, both uninstalled again, a
message pinned and surviving a reload, an automation created, paused and
deleted, the audit trail carrying the call, and a conversation deleted from the
rail.

## Environment facts, current as of this session

- **NVIDIA key is in the OS keychain** at `psok/nvidia`, and `providers.yaml`
  now lists it correctly (a previous session's note said it was missing — it
  isn't; this was fixed). Model `nvidia/nemotron-3-ultra-550b-a55b`. The key
  was pasted into a shell and a transcript at some point in this project's
  history — **rotate it** before relying on this for anything beyond local
  development.
- **No Anthropic or OpenAI key configured.** Those adapters have only ever run
  against mocks; their wire-format translation against the real APIs is
  unverified. If the next session gets a key, that verification is the first
  thing to spend it on.
- **Ollama is not running** on this machine. It is the default embedding
  provider, so the default retrieval path is unexercised; indexing has only
  been verified end to end using NVIDIA embeddings. Starting Ollama and
  running `psok index` against it once would close this gap.
- `sqlite-vec` and FTS5 both work. Bubblewrap is available, so the shell
  sandbox is real and differentially tested.
- **The GitHub connector has a registered OAuth client** and has completed a
  real sign-in (44 tools). Its token needed the `Accept: application/json`
  fix-up in `psok/mcp/oauth.py` to survive: GitHub's token endpoint answers
  form-encoded without it, which the SDK's `OAuthToken.model_validate_json`
  cannot parse.
- **Google Workspace is configured but the redirect URI is the thing to check
  first.** `workspace-mcp` runs its own OAuth on `http://localhost:8765/oauth2callback`
  — *not* PSOK's `:33418` callback, which is GitHub's. That exact URI has to be
  registered on the Google Cloud OAuth client or sign-in ends in
  `redirect_uri_mismatch`.
- **Vercel, Microsoft To Do, LinkedIn and Spotify were added and each was
  started before it shipped.** Verified: Vercel accepts PSOK's *dynamic*
  registration (`POST …/login/oauth/register` → 201), so unlike GitHub it needs
  nothing registered by hand; Microsoft To Do's `sign_in` returns a device code
  and URL; LinkedIn discovers 19 tools; Spotify 22. Spotify is the one still
  needing credentials — a Spotify developer app, entered in its panel.
- **Two were refused, and why.** `lharries/whatsapp-mcp` publishes no package at
  all (clone + a separate Go bridge + QR). Every published WhatsApp server
  instead depends on `better-sqlite3`, which supports Node 20–25 while this
  machine runs **Node 26**, so they exit 1 with no message — recheck when
  `better-sqlite3` ships Node 26 support. `jordanburke/microsoft-todo-mcp-server`
  is broken in **all five** published versions (`Dynamic require of "fs" is not
  supported`); `fabienbutz/microsoft-todo-mcp` shipped in its place and is
  better anyway — it signs in with Microsoft's own public client, so there is no
  Azure app to register.
- Tests: `pytest` (268 unit, 1 skipped by design), `pytest -m live` (5, spawns
  real MCP servers and uses the network), `ruff check psok tests`. Frontend:
  `npm run lint`, `npm run build`, `npm run smoke` (needs a running
  `psok serve` and a configured provider — see `frontend/tests/smoke.mjs`'s
  header comment for `SMOKE_SHELL=0` etc.).

## The GitHub repository

`Wayn-Git/vault` — the name predates PSOK and was never changed because
renaming a repo changes its URL. Currently unarchived and public, with
`master` as the working branch (`dev` is kept in sync but is not where new
work should land unless there's a reason to branch). Topics and description
are set; nothing about the repo's GitHub-side configuration needs attention
right now.

## Where the time goes in a turn, measured

Measured from `execution_logs` on a real browser automation run (conversation
`105aebf8…`, 2026-08-23) before any of the fixes below:

| | |
|---|---|
| Wall clock | 303 s |
| Tool calls | 27 |
| Time in tools | 70 s (23%) |
| **Time in model round trips** | **233 s (77%)** |
| Outcome | died on `max_iterations`, *"iteration limit reached"* |

Browser tools are not the bottleneck — `take_snapshot` averages 30 ms,
`browser_click` 1.1 s. The model is: the same trivial no-tool prompt against
`nemotron-3-ultra-550b` returned in **1.09 s / 8.75 s / 50.23 s** across three
samples. An agent turn costs one model round trip per tool call, so a
fifteen-step browser task multiplies that variance by fifteen.

**Fixed since, with numbers:**

- Recall embedded its query against an Ollama that is not installed. A refused
  connection counted as transient, so it was retried with backoff: **6.09 s,
  twice a turn**. Now asked once and remembered as down — **0.064 s**. The unit
  suite dropped 8.3 s → 2.8 s on the same change.
- Every HTTP call built and closed its own client, so each model call paid a
  fresh TCP+TLS handshake — 26 per browser task. Pooled per event loop: **75%
  less connection overhead**.
- `_unattended_director` claimed to share the live registry and did not
  (`_registry_for(None)` → `cwd()` vs the interface's workspace root). The two
  alternated, so **every automation tick tore down and respawned every MCP
  subprocess**, killing the live browser with them.

**Still open — the 77%.** `providers.yaml` now carries commented Groq and
Cerebras entries; both are OpenAI-compatible (no adapter needed) and free.
Adding a key and pointing the automations at one is the remaining lever, and
the number above is the baseline to beat.

## Planned next steps, roughly in the order they pay for themselves

1. **Rotate the NVIDIA key.** It's the single highest-consequence loose end —
   a real credential known to have touched a shell transcript. Generate a new
   one, `set_secret("psok/nvidia", "...")`, revoke the old one at NVIDIA's end.
2. **Verify Anthropic and/or OpenAI against the real API**, once a key exists.
   The adapters are written and unit-tested against mocks; a single live turn
   against each would either confirm the wire-format translation or surface
   the first real bug in it. This is the most likely place a next session
   finds an actual defect, because it is the one path never exercised for
   real.
3. **Bring Ollama up and run one real indexing pass through it**, to close the
   gap on the default embedding provider. `ollama serve`, then
   `psok index ~/notes --provider ollama`, then `psok search` something and
   read the results by eye.
4. **Register the GitHub OAuth app and switch the connector back on**, if
   GitHub access is wanted. Otherwise leave it off — an unauthenticated,
   permanently-failing connector is worse than an absent one, which is the
   reasoning that turned it off in the first place.
5. **Decide on first-party Gmail/Calendar/Drive integration vs. the MCP
   connector path**, which is currently how those are reached. The open
   question, unresolved on purpose: does their data need to be *synced
   locally* for cross-referencing with the notes vault, or is on-demand access
   through the connector enough? If nothing in a real workflow ever needs
   PSOK to search "my calendar and my notes together" in one query, the
   connector path is sufficient and a first-party layer would be unbuilt
   scope for its own sake.
6. ~~Automation.~~ **Built, as a beta**, and marked beta everywhere it appears.
   Both open questions were answered rather than deferred — see
   [architecture/automation.md](architecture/automation.md). *Who decides it is
   time*: this process, while `psok serve` runs, which makes the rule
   "automations run while PSOK is open". *What the gate does with nobody
   watching*: it denies, collects the operation keys it refused, and the run
   records `blocked` naming them, so the fix is approving one operation rather
   than exempting scheduled work from the gate. Still missing on purpose: cron
   expressions, any trigger other than the clock, retries.
7. **Recurring tasks and background jobs** are the two capabilities most
   often implied by "personal operating system" that this one doesn't have.
   Neither has a design yet. Before writing code: recurring tasks need a
   decision about who evaluates "is it time" — a cron-like process, or a
   check that runs whenever the CLI or API next wakes up — and background
   jobs need the sandbox and permission-gate story extended to something that
   isn't a synchronous tool call inside a turn. Both are real design work, not
   a quick addition.
8. ~~A conversation-delete endpoint.~~ **Built.** `DELETE
   /api/conversations/{id}`, reachable from the `⋯` menu on a rail row. It
   refuses with a 409 while a turn is streaming in that conversation, and takes
   the rows that key on the conversation id as a plain scope string —
   `capability_state`, `memory_state` — with it, since nothing could ever reach
   those again. Extracted memories are deliberately kept: a fact learned in a
   conversation outlives it.

None of the above is committed to a timeline. This is a personal project; the
list is here so the next session (or the one after) doesn't have to
re-derive priority from scratch.

## CORS

**CORS is configured.** The API allows `http://localhost:5173` and
`http://127.0.0.1:5173`. Any other origin needs `PSOK_CORS_ORIGINS` set to a
comma-separated list. It is deliberately not a wildcard: this API runs shell
commands on the machine, so any page the user visits must not be able to drive
it. Verified against a live server with a real `Origin` header, both that the
allowed origin receives `access-control-allow-origin` and that a foreign origin
does not.

## Endpoints

47 endpoints, all verified against a running server.

| Need | Endpoint |
|---|---|
| Conversation list / create | `GET,POST /api/conversations` (scheduled runs excluded; `?include_automations=true` for all) |
| **Rename, or switch provider/model** | `PATCH /api/conversations/{id}` |
| **Delete one** | `DELETE /api/conversations/{id}` (409 while its turn runs) |
| History | `GET /api/conversations/{id}/messages` |
| **Pin a message, and list what is pinned** | `POST /api/conversations/{id}/messages/{message_id}/pin`, `GET /api/conversations/{id}/pins` |
| **Streamed turn** | `POST /api/conversations/{id}/turn` → SSE |
| **Stop a running turn** | `POST /api/conversations/{id}/turn/stop` |
| **Pending confirmations** | `GET /api/confirmations` |
| **Approve / deny** | `POST /api/confirmations/{request_id}` |
| **What runs without asking, and taking one back** | `GET /api/confirmations/preferences`, `DELETE /api/confirmations/preferences/{operation_key}` |
| Skills + connectors with on/off state | `GET /api/capabilities` |
| Toggle one | `POST,DELETE /api/capabilities/{kind}/{name}` |
| `/` autocomplete | `GET /api/skills/search?q=` |
| Every skill, with load errors | `GET /api/skills` |
| **Install a skill from a URL, or delete one** | `POST /api/skills/install`, `DELETE /api/skills/{name}` |
| **Write one from a name, description and instruction** | `POST /api/skills/create` |
| **Browse installable skills** | `GET /api/skills/catalogue` |
| **Every tool the agent can reach** | `GET /api/tools` |
| **A file from the browser, as a path** | `POST /api/attachments` |
| Tasks and calendar, read-only | `GET /api/tasks`, `GET /api/calendar` |
| Connector catalogue | `GET /api/mcp/catalogue` |
| Configured connectors | `GET /api/mcp/servers` |
| Add / remove a connector | `POST,DELETE /api/mcp/servers` |
| Attach a hand-registered OAuth app | `POST /api/mcp/servers/{name}/oauth-client` |
| **Credentials a stdio server takes through the environment** | `POST /api/mcp/servers/{name}/env`, `DELETE /api/mcp/servers/{name}/env/{key}` |
| **Sign in, or switch account** | `POST /api/mcp/servers/{name}/login` `{force, account_hint}`, `GET /api/mcp/authorizations` |
| **Sign out, so the next sign-in asks which account** | `POST /api/mcp/servers/{name}/logout` |
| Connect one now | `POST /api/mcp/servers/{name}/connect` |
| **Remembered facts, and the memory switch** | `GET /api/memory`, `POST /api/memory/toggle`, `DELETE /api/memory/{id}` |
| **Automations (beta): list, create, retime, delete** | `GET,POST /api/automations`, `PATCH,DELETE /api/automations/{id}` |
| **Run one now, on the scheduler's path** | `POST /api/automations/{id}/run` |
| **Every kept run of one automation** | `GET /api/automations/{id}/runs` |
| **Start every switched-on connector now** | `POST /api/mcp/reconcile` |
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
  or hide, but **never** as the answer. The interface streams it live into its
  own panel and folds that panel away when the answer starts.
- `assistant_text` — `{text}`, the whole answer at once
- `tool_call` — `{name, arguments}`
- `confirmation_required` — `{request_id, tool_name, operation_key, risk, reason,
  arguments, conversation_id}`, the turn is suspended until this is answered
- `tool_result` — `{name, content, is_error}`
- `warning` — `{message}`, e.g. the stream was cut off, or the loop is
  continuing a turn that came back empty or truncated
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

**A turn does not end just because the model stopped.** If the model returns
no text (common right after a tool result) or a provider-truncated response,
the loop appends a continuation instruction to its *next* call only and tries
again, up to `Guards.max_continuations` (2). The interface sees this as a
`warning` frame, not a premature `done` — it should keep the composer disabled
and keep listening rather than treating the warning as terminal.

**A turn stops counting as running at its terminal frame.** `_active_turns`
releases on `done`/`error`/`guard`, not when the stream closes — memory
extraction runs after `done` and is not part of the turn anyone can stop.
Holding the registration across it left the conversation looking busy for
seconds after the reply had landed, long enough that deleting it came back a
409.

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

**Terminal means terminal, not "when the stream closes".** The stream stays open
past `done` for the `memory` frame, which is a second model call and can take
seconds. An interface that waits for the close before releasing the composer
shows a finished answer with a "thinking" line still under it. Release on the
terminal frame and keep reading.

## The confirmation flow, which is the part worth getting right

A medium- or high-risk tool call **suspends the turn**. The stream stays open and
announces it: a **`confirmation_required` frame** arrives after `tool_call`,
carrying `request_id`, `tool_name`, `operation_key`, `risk`, `reason`,
`arguments` and `conversation_id`. The UI must:

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

`conversation_id` on the pending payload exists because prompts are process-
wide: an interface recovering one after a reload has to know whether the
suspended turn is the conversation on screen or a different one, and must not
raise a foreign prompt as a blocking modal over an unrelated transcript.

`remember: true` persists a standing approval keyed by `operation_key` — 
`run_shell_command:read-only` rather than `run_shell_command`. That
distinction is load-bearing: approving a read-only shell command must not
approve a destructive one. Show the user what they are about to remember, not
just the tool name. Standing approvals can be listed and revoked at
`GET,DELETE /api/confirmations/preferences[/{operation_key}]`, and the same
thing is available from `psok permissions [--revoke KEY]`.

Every MCP server also requires a one-time trust confirmation on first use, so
expect two prompts the first time someone uses a new connector.

## What the interface does with all of this

1. **Conversations** — create, list, rename (`F2` or the row's `⋯` menu),
   delete (same menu, behind a confirming second click), filter, switch with
   `⌘↑`/`⌘↓`; the open one survives a reload. Listed in the rail alongside
   Tasks, Skills, Connectors, Memory and Activity, with Settings at the foot.
2. **Streaming** — `assistant_delta` rendered as markdown while it arrives,
   `reasoning_delta` streamed live into its own panel that folds itself away
   when the answer starts, `done.text` deliberately not rendered. The transcript
   is never refetched when a turn ends — reasoning, warnings and the memory note
   are stream-only and a refetch deletes them.
3. **Confirmations** — the `confirmation_required` frame raises an inline
   prompt showing the arguments and the operation key, answerable with
   `Enter` / `Escape` / `R`. `GET /api/confirmations` is the reload-recovery
   path only, and a recovered prompt for a different conversation is shown as
   a banner with a link to it rather than a blocking modal.
4. **Skills and connectors** — **one page, two tabs** (`⌘3`), because they are
   the same kind of thing and were three surfaces: a Skills view, a Connectors
   view, and a Directory overlay that browsed both. Adding is now done where
   managing is done. The Skills tab lists installed and installable together and
   offers three ways in — **New skill** (name, description, instruction; the
   backend composes and validates the `SKILL.md`), a link to any `SKILL.md`, or
   a catalogue card. The Connectors tab separates **Connected** from **Added,
   not running**, so a connector that has never once worked is not listed beside
   four that are serving tools; below both, the catalogue as plain icon-and-name
   rows. Before the first turn nothing has reconciled, so rather than reporting
   six connectors as "not running" it says "not started yet" and offers one
   button (`POST /api/mcp/reconcile`) that starts them. Also reachable from the
   composer's `+` menu (with a "Tool access" flyout listing every reachable tool
   by source and risk) and the palette (`⌘K`), all reading one store, so a
   connector reports what is running rather than what was switched on.
5. **`/` autocomplete** — backed by `/api/skills/search`; the marker is left in
   the message for the backend to parse and strip.
6. **Connector setup** — a connector is a row you *open*, not a row of four
   controls. The detail page carries a **Connection** block (who it is signed
   in as, Reconnect, Sign out), the credentials form, every action the
   connector actually exposes with its risk, and an Information table. Sign-in
   state is read from the store that really holds it: a stdio server keeps its
   own accounts, so PSOK's keychain is the wrong place to ask, and asking it
   anyway is what made a Google connector with no account attached report
   itself signed in.
7. **Audit, permissions and memory** — the trail with an optional follow mode;
   the standing approvals with a revoke button, in Settings → Permissions; and
   the standing facts with a switch and a way to retire one.
8. **Attachments** — a file dropped, pasted, or picked (`⌘U`) into the
   composer uploads to `~/.psok/attachments/<id>/<name>` and the message
   carries the path for the ordinary file tools to read.
9. **Plan mode** — a composer toggle that prepends an instruction asking for
    the steps before anything is written or run; not a backend concept, a
    phrasing shortcut kept honest by being exactly that.
10. **Automations (beta)** — `⌘4`. A prompt and an interval, run as an ordinary
    turn in a conversation of its own, while the server is up. Marked beta in
    the rail, on the page, and in the API payload. The page states both beta
    positions rather than burying them. Each run's conversation carries
    `automation_id`, is **excluded from the rail** — 31 of 111 conversations
    were runs, and the rail lists a fixed 50, so they pushed real conversations
    off the end — and is listed instead under its automation
    (`GET /api/automations/{id}/runs`), which is also the only way earlier runs
    were ever reachable. Twenty are kept per automation. Unattended runs stream
    and get 30 iterations rather than 12.
11. **Pins** — a message header's pin, or `⌘P` on the newest one, with a strip
    above the transcript that jumps to any of them. Deliberately inert: not sent
    to the model, does not change recall, does not reorder history. A column on
    `messages`, written against the database row id, so a message still
    streaming cannot be pinned until the transcript is read back.

## What is deliberately still not built

- **Projects, artifacts, plugins, voice input, a "cowork" mode.** Nothing in
  PSOK backs them, and a menu row that opens nothing is worse than an absent
  one. Not ruled out forever — just not built until something in the
  architecture would actually support them.
- **Screenshot capture from the composer.** There is no portable way to take
  one on Linux without assuming a compositor; the Playwright connector takes
  page screenshots today, which covers the actual use case (showing the model
  a web page) without solving the harder, less useful problem (a desktop
  screenshot tool).
- **Extended-thinking toggles.** Provider-specific thinking budgets are
  absorbed inside each adapter and not exposed as a setting.
- **Pins that mean anything to the model.** A pin is a bookmark, full stop.
  Feeding pinned messages back into the prompt, or weighting recall by them, is
  a different feature that would need its own design — and shipping it under the
  same word would make "pin this" silently mean "change the conversation".
- **Anything multi-user.** Out of scope by design (ADR-0001).
- **Automations that can answer a permission prompt.** They deny instead, and
  say what they denied. Changing that needs its own design, not a flag.
- **Recurring tasks and background jobs.** See item 7 in the plan above —
  these are the two most likely to get built next, once designed.

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
More recently, the agent loop ending a turn on an empty or truncated model
reply was found the same way — by actually asking it to do a multi-step task
and watching it stop partway, not by reading the loop's code and assuming it
was fine.

**Mutation-check regression tests.** Reintroduce the bug and confirm the test
fails. A test that cannot fail protects nothing.

**Tests must not read the developer's machine.** `conftest.py` isolated
`PSOK_HOME` but not the OS keychain, so every credential test read and wrote
the real login keyring: one assertion passed or failed depending on whether
the person running it happened to be signed into GitHub, and a full `pytest`
run deleted a real GitHub token. Both are fixed by an in-memory keyring in the
autouse fixture. Any new store PSOK writes to needs the same treatment.

**Read this file before starting work, and update it before ending a
session.** It exists so state does not have to be re-derived from git log and
memory every time. If something here turns out to be stale, fix it in place
rather than leaving the next session to discover the drift the hard way.
