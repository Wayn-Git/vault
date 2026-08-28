# PSOK — next session

Working plan, not eulogy. API contract below is the reference.

## What exists (verified end to end)

Multi-provider AI runtime (NVIDIA NIM live-tested, Ollama configured, OpenAI-compatible
fallback) with streaming + retry. Agent loop with iteration/time/repetition/**continuation**
guards — empty or truncated turns continue, not silently end. 20 builtin tools (fs, shell,
desktop, tasks, calendar, doc search, web). MCP with OAuth 2.1 + PKCE, catalogue, SSRF
protection, per-server circuit breaking. Permission gate with Bubblewrap sandbox. Hybrid
retrieval over notes vault (BM25 + vector, incremental). Long-term memory extracted per turn.
Markdown skills, installable from URL / browsed / written from 3 fields. Full React UI served
by same process (`psok serve`). Standing approvals in UI+CLI. Full CLI.

**Verified:** 457 unit tests, `ruff` clean, 53-check Playwright suite (`frontend/tests/smoke.mjs`)
driving real browser + real server + real model — streaming, markdown-once, thinking live/folds,
permission gate on keyboard, skill install/uninstall, pin survives reload, automation
create/pause/delete, audit trail, conversation delete.

## Environment facts

- **NVIDIA key** in OS keychain `psok/nvidia` (also in `providers.yaml`). Model
  `nvidia/nemotron-3-ultra-550b-a55b`. Key touched a shell transcript — **rotate it**.
- **No Anthropic/OpenAI key.** Adapters only ran vs mocks; real wire-format unverified.
- **Ollama not running.** It's the default embedding provider, so default retrieval path
  unexercised; indexing only verified with NVIDIA embeddings. `ollama serve` + `psok index`
  would close it.
- `sqlite-vec` + FTS5 work. Bubblewrap available (shell sandbox real, differentially tested).
- **GitHub connector:** OAuth client registered, real sign-in done (44 tools). Needed
  `Accept: application/json` fix in `psok/mcp/oauth.py` (GitHub returns form-encoded w/o it)
  and `auth_timeout_seconds` (sign-in was given the server's 60s deadline; `ServerConfig` now
  separates server-answer time from human-sign-in time).
- **Google** client secret stored + accepted. Rotate **the secret from the transcript** (plain
  text in chat log). One secret per *account group* (9 Google connectors share one client) —
  not editable from Connectors menu (409); replace in terminal:
  `psok mcp env <server> GOOGLE_OAUTH_CLIENT_SECRET <value> --secret --force`.
  Validated on entry (`GOCSPX-` + 28) + verified against token endpoint pre-browser.
- **Google Workspace** signs in via `http://localhost:8765/oauth2callback` (not PSOK's `:33418`,
  which is GitHub's). Fixed: `workspace-mcp` was killed when browser opened (port held by
  nothing); redirect-uri must be registered on Google Cloud client; `WORKSPACE_MCP_PORT_FALLBACK_COUNT: "0"`
  makes port-walk fail loudly (backfilled in `_fill_catalogue_env`).
- **Vercel, MS To Do, LinkedIn, Spotify** added + started before shipping. Vercel accepts
  dynamic registration (201) — nothing to register by hand. To Do returns device code. LinkedIn
  19 tools, Spotify 22 (needs a Spotify dev app).
- **Refused:** WhatsApp servers all need `better-sqlite3` (Node 20–25; this box runs **Node 26**
  → exit 1) — recheck when it ships 26 support. `jordanburke/microsoft-todo-mcp-server` broken in
  all 5 versions; `fabienbutz/microsoft-todo-mcp` shipped instead (uses Microsoft's public client).
- **Tests:** `pytest` (457 unit, 1 skipped), `pytest -m live` (5), `ruff check psok tests`.
  Frontend: `npm run lint` / `build` / `smoke` (needs running `psok serve` + provider).

## Traps (reproduced live; plausible errors pointed away from cause)

- `sign_out` deleted shared OAuth state store (`oauth_states.json` = workspace-mcp CSRF store in
  the 9-connector shared credentials dir) → "Invalid or expired OAuth state" blaming Google.
  `IN_FLIGHT_FILES` now preserved.
- Published sign-in link outlived its state (5–10 min TTL vs persistent URL). `PendingAuthorization`
  now has TTL; API sends no URL once lapsed.
- Connect deadline shorter than human — `auth_timeout_seconds` separates them.
- Server's own OAuth killed mid-flow by `manager.shutdown()` in `finally`; session now owned by
  watcher task.
- Context budget counted tool calls as 0 tokens (`content` null) → silent history overflow +
  provider failure mid-generation. `message_tokens` counts serialized calls.
- Provider error inside a stream dropped (OpenAI-compat `{"error":…}` frame over open 200 matched
  nothing) → refusal became empty turn. Now surfaced.
- Workspace root was registry's cache key; non-turn callers pass `None` → `cwd()`/workspace
  alternated, tearing down+respawn all MCP each turn. Root belongs to builtin file tools;
  `MCPManager.rebind` moves live connections.
- Dropped MCP connection never recovered (dead pipe, `connected` stays true). Transport failure
  now reconnects once + retries.
- `login` blocked whole flow (up to 5 min). Now answers `202` in ms via
  `GET /api/mcp/authorizations`.

## GitHub repo

`Wayn-Git/vault` — name predates PSOK, kept (rename changes URL). Public, unarchived,
`master` working branch (`dev` synced only). Topics/description set. Nothing to do.

## Where turn time goes (measured, browser run `105aebf8…`)

Wall 303s. Tools 70s (23%). **Model round trips 233s (77%)**. Died on `max_iterations`.
Browser tools not the bottleneck (`take_snapshot` 30ms, `browser_click` 1.1s); model is
(1.09/8.75/50.23s for same trivial prompt). 1 round trip per tool call → 15-step task × 15.

**Fixed since:** recall embedded against missing Ollama → 6.09s×2/turn → now 0.064s (unit suite
8.3→2.8s); HTTP clients pooled per event loop (−75% conn overhead); `_unattended_director`
didn't share live registry (each automation tick respawned all MCP, killing browser).

**Still open (the 77%):** pointing the loop at a fast provider is the lever, and as of
Phase 3 that is now one screen rather than a YAML edit — Settings > Models, or
`psok providers add groq` then `psok secrets set psok/groq`. The starter file is
generated from the catalogue, so the drift `psok doctor` reported cannot recur; this
box's existing `providers.yaml` still predates it, so run `psok providers add` there.
**Nobody has actually put a Groq or Cerebras key in yet — that is the next lever.**

## Remaining work — phases 4 and 5

Phases 1 (tasks + To Do) and 2 (turns that resolve, Stop) are **done and
live-verified 2026-08-27**; phase 3 (providers and fallback) is **done and
live-verified 2026-08-28**. What follows is written for whoever picks this up.
Order is payoff order; each phase is independently shippable and has its own
verification. Do not start the next until the current one's checks pass.

Context and measurements: [AUDIT-2026-08-27.md](AUDIT-2026-08-27.md),
[architecture/tasks.md](architecture/tasks.md),
[architecture/turns.md](architecture/turns.md),
[architecture/providers.md](architecture/providers.md).

### Phase 3 — providers and fallback — **DONE, verified 2026-08-28**

Built and live-verified. Full write-up: [architecture/providers.md](architecture/providers.md).
The abstraction was not rewritten — `ChatClient`, `ResolvedModel`, the registry
and the OpenAI-compatible fall-through are unchanged.

- **3.1 Catalogue.** `psok/provider_catalogue.py`, 13 presets (Ollama, Groq,
  Cerebras, OpenAI, Anthropic, Google, OpenRouter, xAI, DeepSeek, Mistral,
  Together, Fireworks, NVIDIA). The starter `providers.yaml` is now **generated
  from it**, so the drift `psok doctor` reported cannot recur. No `auth_style`
  field: PSOK already has native adapters for the two providers that need one,
  so it would be a slot nothing reads.
- **3.2 Settings writes the file.** `providers.yaml` had no write path at all;
  it now has `save_providers` / `add_provider` / `remove_provider` plus
  `GET,POST /api/providers` and `DELETE /api/providers/{name}`. Settings →
  Models lists what is configured with a per-row state, offers the rest of the
  catalogue, and takes a key. **No route returns a key.** `psok secrets` — cited
  by the docs and the starter file since before it existed — is now real, and
  prompts rather than taking the key as an argument (an argument lands in shell
  history, which is how two keys ended up needing rotation).
- **3.3 Availability.** `psok/runtime/availability.py`. Keyless endpoints are
  probed once and cached (60s); everything else is presumed available until a
  turn proves otherwise (300s). `/api/health` gained `providers_unavailable`.
  Unavailable providers stay listed with a reason rather than vanishing.
- **3.4 Declared context windows.** `context_window` on `ProviderConfig`, honoured
  by all four adapters, guess kept as fallback. **`budget_history` now counts
  tool schemas** — the 29,620 tokens it never saw — and the director builds the
  schemas before budgeting rather than after.
- **3.5 Taxonomy.** `psok/runtime/failures.py`: `FailureKind` with retry and
  fallback as *separate* decisions. Quota-exhausted 429 is non-retryable but
  fallback-worthy; a 404 is neither. `ProviderStreamError` moved to
  `runtime/http.py` beside `ProviderHTTPError`, both now `ProviderError`
  subclasses carrying `kind`/`status`/`body`. The one string-matching consumer
  (`embeddings.py`'s `if "unreachable" in str(exc)`) reads the field now.
- **3.6 The chain.** `psok/runtime/chain.py`. Order from `providers.yaml`, or a
  top-level `fallback:` list. Capped at two fallbacks. **One shared
  `AttemptBudget`**, not `MAX_RETRIES` per link. History **re-budgeted for the
  fallback model's own window**. One `warning` frame: *"nvidia was unreachable —
  answering with groq/llama-3.3-70b instead"*. `active` moves forward only, so a
  dead provider is not re-tried each iteration. Memory extraction now uses the
  model that answered, not the one on the conversation row.

**Verified** exactly as this section asked: two providers over real HTTP (live
`http.server` + a dead port, no mocked transport) — primary unreachable answered
by the fallback in 2.1s with one warning line naming both; primary returning 404
failed in 0.00s with no fallback attempt. Plus a live `psok serve` run of the new
routes. 39 new tests, 457 in the suite, `ruff` clean, frontend lint + build clean.

**Left undone on purpose:** per-conversation fallback order (the order is global;
per-conversation needs a column, a PATCH field and a control, and a column
nothing writes is a reserved slot).

### Phase 4 — connector setup that finishes itself

Most of the latency work here is **already done** (2026-08-27): `connect_all` is
concurrent and non-interactive, a stale token no longer buys a 300s callback
wait, and health separates `connectors_awaiting_sign_in` from real faults.
Measured **>115s → 3.9s**. What is left is the experience.

4.1 **Withhold the tools of a connector that is connected but not signed in.**
`registry.schemas()` already has the `hidden_servers` mechanism; auth state
should feed it too. This is what stops the model calling Gmail, getting
`Connection closed`, inventing a service outage and handing the work back — the
original reported bug.

4.2 **Turn a connector failure into an instruction.** The model currently sees
the raw exception string. Name the connector, the screen and the button.
`BASE_PROMPT`'s "errors are information" is too general to act on.

4.3 **One state machine per connector** — `Adding → Authenticating → Setting up
→ Syncing → Ready`, or `Failed` with the reason and a Retry — driven off the
existing `GET /api/mcp/authorizations` poll in `ConnectorsTab.jsx`. Adding a
connector should run its whole setup, including a first sync for microsoft-todo.

4.4 **Collapse the five Google connectors into one `workspace-mcp` process**
(`--tools gmail calendar drive docs sheets`). They already share one OAuth
client, one credentials directory and one callback port; five processes over one
account is what created the shared-state traps above. `google-calendar:
Connection closed` still recurs intermittently under concurrent startup and
self-heals on reconcile. **This is a config migration touching a working Google
sign-in — do it deliberately, not as a side effect.**

**Verify:** from a cold `psok serve` with `github` unauthorised, an automation
run reaches the model rather than spending its budget on a browser nobody
opened. Add a connector from the UI and confirm it reaches Ready with no second
page visited.

### Phase 5 — two real modes, and a system that says what it is doing

5.1 **Plan mode is currently eight lines in one file.** `Chat.jsx:496` prepends
a sentence, and that sentence is **persisted into the transcript** and replayed
on every later iteration and every later turn. The backend has zero references
to it; tool schemas, the permission gate and dispatch are all identical, so
nothing stops a write except the model choosing to obey prose.

Make it a field on `TurnRequest`, not a string glued to the message. `Director`
takes a `mode`. In plan mode the first call withholds the write and shell tools
**from `tool_schemas`** — enforced by the registry, not asked for politely — and
returns a structured step list as a `plan` frame. The UI renders the steps; the
user approves, edits or discards; on approval the same Director continues with
the full tool set, emitting `step_started` / `step_done`.

Decided with the user: **explicit toggle, no classifier, no auto-escalation.**
Chat mode stays a single fast pass and pays nothing. (khoj's
`aget_data_sources_and_output_format` is the router *not* to build here — it
costs a round trip on every message.)

5.2 **A `status` frame** carrying a named state: thinking, planning, searching,
using a connector, running a tool, generating, retrying, switching provider,
syncing, completed, cancelled, failed. Every one of these already exists inside
the loop and none is visible.

5.3 **A turn-cost line** — `12 steps · 4 tools · 2m 14s`.
`execution_logs.duration_ms` already holds everything needed and nothing reads
it. Cheapest observability in the codebase.

5.4 `Chat.jsx`'s reducer ends in `default: break`, silently dropping unknown
event types. Log them, so a frame added on the server is never invisible again.

**Verify:** same request in both modes — chat answers in one pass; plan returns
a step list, writes nothing until approved, and a `write_file` attempt during
the plan call is refused *by the registry* rather than declined by the model.

### Known limitations, proven not assumed (2026-08-27)

Both were checked against the real account, not the API docs. Neither is a PSOK
bug and neither has a fix from this side:

- **My Day cannot sync.** A To Do task known to be in My Day ("Sift project")
  comes back from `graph.microsoft.com/v1.0/…/todo` with exactly `id, title,
  status, importance, isReminderOn, createdDateTime, dueDateTime, body,
  categories, lastModifiedDateTime, hasAttachments, @odata.etag` — on the list
  fetch *and* on `get_task` with checklist and linked resources expanded. There
  is no My Day field under any name. PSOK's My Day is therefore local, every row
  carries a sun toggle to fill it, and the page says so.
- **`list_task_lists` returns 3 lists where the To Do app shows 4.** "Getting
  started" (7 tasks) is not returned, with `hasMore: false` and
  `maxResults: 100`. Likely a client-side onboarding list not backed by Graph.
  If a first-party Microsoft integration is ever built (step 5 below), this is
  one of the things it would fix.

Related fix made while proving this: `_paged` looked for `nextCursor`/`cursor`
and this server signals `hasMore`, so a truncated page was indistinguishable
from a complete one — and `_retire_missing` cancels every task a pull did not
see. It now raises `TruncatedListing` and skips retirement rather than
cancelling real tasks.

## Next steps (roughly in payoff order)

0. **Finish Google sign-in** — human half only (press Connect, approve). Preflight passes, URL
   published with TTL, `8765` held.
1. **Rotate NVIDIA key + Google secret** (both touched a transcript). Highest-consequence loose end.
2. **Verify Anthropic/OpenAI live** once a key exists — most likely place for a real defect
   (only path never exercised for real). Now `psok providers add anthropic` + `psok secrets set
   psok/anthropic`, or Settings > Models.
3. **Bring Ollama up + one real indexing pass** — closes default-embedding gap.
4. **GitHub connector** — register app + re-enable only if wanted; absent beats permanently-failing.
5. **Decide** first-party Gmail/Calendar/Drive vs connector path. Open: does data need *local sync*
   to cross-reference with the vault, or is on-demand enough? (unresolved on purpose)
6. ~~Automation~~ **Built (beta)** — runs while `psok serve` is open; unattended gate denies +
   records blocked ops. Missing on purpose: cron, non-clock triggers, retries. See
   [architecture/automation.md](architecture/automation.md).
7. **Recurring tasks + background jobs** — two capabilities most implied by "personal OS" that
   aren't built; neither has a design. Real design work, not a quick add. Note Graph *does*
   expose `recurrence` on a task and PSOK never requests it, so the To Do half is readable
   whenever someone designs the local half.
8. ~~Conversation delete~~ **Built.** `DELETE /api/conversations/{id}` (409 while turn streams),
   takes keyed rows with it; memories deliberately kept.

No timeline — personal project, list is so the next session doesn't re-derive priority.

## CORS

Allows `http://localhost:5173` + `http://127.0.0.1:5173`; else `PSOK_CORS_ORIGINS` (CSV).
Deliberately not wildcard (API runs shell). Verified live.

## Endpoints (54, all verified)

| Need | Endpoint |
|---|---|
| List/create convs | `GET,POST /api/conversations` (`?include_automations=true` for all) |
| Rename / switch provider-model | `PATCH /api/conversations/{id}` |
| Delete one | `DELETE /api/conversations/{id}` (409 while turn runs) |
| Delete all | `DELETE /api/conversations` (409 if any turn runs) |
| History | `GET /api/conversations/{id}/messages` |
| Pin / list pins | `POST /api/conversations/{id}/messages/{message_id}/pin`, `GET /api/conversations/{id}/pins` |
| Streamed turn | `POST /api/conversations/{id}/turn` → SSE |
| Stop turn | `POST /api/conversations/{id}/turn/stop` |
| Pending confirmations | `GET /api/confirmations` |
| Approve/deny | `POST /api/confirmations/{request_id}` |
| Standing prefs / revoke | `GET /api/confirmations/preferences`, `DELETE /api/confirmations/preferences/{operation_key}` |
| Providers + catalogue | `GET /api/providers` (configured, with `has_key`/`available`; never a key) |
| Add/update a provider | `POST /api/providers` `{name, base_url?, default_model?, context_window?, api_key?}` — key goes to the keychain |
| Remove a provider | `DELETE /api/providers/{name}` (entry only; the key stays) |
| Skills+connectors state | `GET /api/capabilities` |
| Toggle one | `POST,DELETE /api/capabilities/{kind}/{name}` |
| `/` autocomplete | `GET /api/skills/search?q=` |
| All skills + load errors | `GET /api/skills` |
| Install from URL / delete | `POST /api/skills/install`, `DELETE /api/skills/{name}` |
| Write from 3 fields | `POST /api/skills/create` |
| Browse installable | `GET /api/skills/catalogue` |
| Every tool | `GET /api/tools` |
| File as path | `POST /api/attachments` |
| Tasks / calendar | `GET /api/tasks`, `GET /api/calendar` |
| Add/change/cancel task | `POST /api/tasks`, `PATCH,DELETE /api/tasks/{id}` (writes to MS To Do when connected) |
| Abandon sign-in | `DELETE /api/mcp/servers/{name}/login` |
| Pull To Do now | `POST /api/tasks/sync` |
| Connector catalogue | `GET /api/mcp/catalogue` |
| Configured connectors | `GET /api/mcp/servers` |
| Add/remove connector | `POST,DELETE /api/mcp/servers` |
| Attach hand-registered OAuth | `POST /api/mcp/servers/{name}/oauth-client` |
| Env creds (stdio) | `POST /api/mcp/servers/{name}/env`, `DELETE /api/mcp/servers/{name}/env/{key}` |
| Sign in / switch account | `POST /api/mcp/servers/{name}/login` `{force, account_hint}` → **202, non-blocking**; watch `GET /api/mcp/authorizations` for `status`/`authorization_url`/`expires_in` |
| Sign out | `POST /api/mcp/servers/{name}/logout` |
| Connect now | `POST /api/mcp/servers/{name}/connect` |
| Memory | `GET /api/memory`, `POST /api/memory/toggle`, `DELETE /api/memory/{id}`, `DELETE /api/memory` (all) |
| Automations (beta) CRUD | `GET,POST /api/automations`, `PATCH,DELETE /api/automations/{id}` |
| Run now (scheduler path) | `POST /api/automations/{id}/run` |
| Runs of one | `GET /api/automations/{id}/runs` |
| Start all switched-on now | `POST /api/mcp/reconcile` |
| Audit trail | `GET /api/logs` |
| Health | `GET /api/health` |

`POST/PATCH /api/conversations` reject unknown provider (400). `/api/health` returns
`provider_defaults` (for prefill), `providers_unavailable` (`{name: reason}` — configured and
not answering; listed, not hidden), live registry after a turn runs, `connector_errors`; `status`
`degraded` when that map non-empty.

## Turn stream

**No `EventSource`** — endpoint is POST. Use `fetch` + `ReadableStream` reader, parse `data:` lines.

Frames (`data: {json}`):
- `assistant_delta {text}` — append
- `reasoning_delta {text}` — stream to own panel, fold away when answer starts; **never as answer**
- `assistant_text {text}` — whole answer (non-streaming providers)
- `tool_call {name, arguments}`
- `confirmation_required {request_id, tool_name, operation_key, risk, reason, arguments, conversation_id}` — turn suspended until answered
- `tool_result {name, content, is_error}`
- `warning {message}` — stream cut off / turn continuing an empty reply / **provider fell back**
  (*"nvidia was unreachable — answering with groq/llama-3.3-70b instead"*, one line, not terminal)
- `guard {reason}` — loop limit / user stop
- `error {message}` — always last
- `done {text, iterations}`
- `memory {created, superseded}` — **after** `done` (extraction is a 2nd model call)

**Answer arrives exactly once.** Streaming → deltas, no `assistant_text`; non-streaming →
`assistant_text`, no deltas. **Do not render `done.text`** (repeats final answer → double-render).

**A turn doesn't end when model stops.** Empty/truncated reply appends continuation instruction
to *next* call, retries up to `Guards.max_continuations` (2). Seen as `warning`, not `done` —
keep composer disabled, keep listening.

**Turn stops running at terminal frame.** `_active_turns` releases on `done`/`error`/`guard`, not
stream close (memory extraction runs after and isn't stoppable).

**Stop ≈ 1s** (measured live). Cancel raced against the model call *and* each streamed chunk, and
propagates into httpx. Cancelling a tool call cancels the work, not just the waiter — an abandoned
call used to block the next call to that connector. Shell subprocesses are killed, not orphaned.

**Stop is a request, not an abort.** Aborting fetch leaves loop running. Use `/turn/stop`; ends in
`guard` "stopped by the user". Let stream close itself.

**Failed turn = `error` event, not dead conn.** Treat `error`/`guard`/`done` as terminal,
re-enable composer on all three + stream close.

**Terminal = terminal, not stream close.** Stream stays open past `done` for `memory` frame.
Release on terminal frame, keep reading.

## Confirmation flow (the part worth getting right)

Medium/high-risk tool call suspends turn; `confirmation_required` arrives after `tool_call`.
UI: 1) render prompt 2) `POST /api/confirmations/{request_id}` `{allow, remember}` 3) stream resumes.

`GET /api/confirmations` = reload-recovery only. Event exists because polling can't answer:
- not every `tool_call` confirms (low-risk run silently),
- two pending calls to same tool indistinguishable by name (event carries request_id).

`conversation_id` on pending payload: prompts are process-wide, so a reloaded UI knows whether the
suspended turn is on-screen before raising a blocking modal.

`remember:true` keys by `operation_key` (`run_shell_command:read-only`, not `run_shell_command`) —
approving read-only must not approve destructive. Show what's being remembered. Revoke at
`GET,DELETE /api/confirmations/preferences[/{operation_key}]` or `psok permissions [--revoke KEY]`.

First use of any MCP server needs a one-time trust confirmation — expect two prompts.

## Interface behavior

1. **Conversations** — create/list/rename (`F2`/`⋯`)/delete (2-click confirm)/filter/switch (`⌘↑↓`);
   open one survives reload. Rail: Tasks, Skills, Connectors, Memory, Activity; Settings at foot.
2. **Streaming** — deltas as markdown, reasoning live + folds, `done.text` not rendered.
   Never refetch transcript at turn end (would delete stream-only reasoning/warnings/memory note).
3. **Confirmations** — inline prompt, `Enter`/`Esc`/`R`; `GET /api/confirmations` only for
   reload-recovery; foreign-conversation prompt = banner with link, not blocking modal.
4. **Skills+connectors** — one page two tabs (`⌘3`). Skills tab: installed+installable together,
   3 ways in (New skill / SKILL.md link / catalogue card). Connectors: **Connected** vs **Added,
   not running** (never-worked not beside working); catalogue as icon+name rows. Pre-first-turn
   says "not started yet"+ `POST /api/mcp/reconcile`. Also via composer `+` (Tool access flyout)
   + palette `⌘K`, one store (reports what runs, not what was switched on).
5. **`/` autocomplete** — via `/api/skills/search`; marker left for backend to strip.
6. **Connector setup** — row you *open*. Connection block (who signed in / Reconnect / Sign out),
   credentials form, actions+risk, info table. Sign-in state read from the real store (stdio
   server keeps own accounts; asking keychain is what made a Google conn with no account report
   itself signed in).
7. **Audit/permissions/memory** — trail w/ follow mode; standing approvals w/ revoke
   (Settings→Permissions); facts w/ switch + retire.
8. **Attachments** — drop/paste/pick (`⌘U`) → `~/.psok/attachments/<id>/<name>`, message carries path.
9. **Plan mode** — composer toggle prepending "steps first" instruction; phrasing shortcut, not
   backend. **Phase 5 replaces this** — the prefix also lands in the transcript and is replayed
   every later turn.
10. **Automations (beta)** — `⌘4`. Prompt + interval, runs as normal turn in own conversation while
    server up. Run conversations carry `automation_id`, **excluded from rail** (31/111 were runs,
    rail fixed at 50) + listed under `GET /api/automations/{id}/runs`. 20 kept. Unattended: 30
    iterations vs 12.
11. **Reminders** — first unsolicited thing. 30s tick scans `COALESCE(reminder_at, due_at)`,
    fires `notify-send`/`osascript`/PowerShell. `reminded_at` claimed w/ conditional update
    *before* notify (no dupes, no loop on no-notifier). Fire only while open. Local naive timestamps
    throughout (UTC compared = late by offset).
12. **MS To Do is where tasks go** — write Graph first, local row = mirror (carries Graph id). No
    account → local + says so; write fail → task still local + answer says it didn't reach To Do.
    Push-then-pull every ~15min via live registry (no 2nd process/sign-in), upsert on
    `(external_source, external_id)`. **Two-way since 2026-08-27**: a local edit sets `dirty_at`
    and the push half sends it before the pull, which is what removes the need for a merge
    algorithm. Lists mirrored; names matched past leading emoji (`🛒 Groceries` answers to
    "groceries"). Buckets — My Day / Missed / Important / General — are queries, never stored
    state. See [architecture/tasks.md](architecture/tasks.md).
13. **Settings→Models** — writes `providers.yaml` rather than describing it. Configured rows carry
    `ready` / `needs a key` / `not answering`; the rest of the 13-entry catalogue is one Add each,
    plus a row for any OpenAI-compatible endpoint. Key goes to the keychain and no route hands one
    back. Remove drops the entry and **keeps the key** (`psok secrets delete` is the other decision).
14. **Settings→Data** — clear convs or facts, each behind 2-click confirm + count first. Tasks,
    audit, index, creds untouched.
15. **Pins** — header pin or `⌘P`; strip above transcript. Deliberately inert (not sent to model,
    no recall effect). Column on `messages`; streaming msg can't pin until read back.

## Deliberately not built

Projects/artifacts/plugins/voice/"cowork" (nothing backs them; absent > dead row). Screenshot from
composer (no portable Linux w/o compositor; Playwright covers the real case). Extended-thinking
toggles (absorbed in adapters). Pins-that-mean-something (would be a different feature). Anything
multi-user (ADR-0001). Automations answering permission prompts (deny + report). Recurring tasks
(no schema slot; reminders ≠ recurrence). Two-way task sync — **built 2026-08-27** (`dirty_at`
push-then-pull avoids merge algo; lists mirrored; vanished tasks stay `cancelled` not deleted).
Notification delivery guarantees (best-effort `notify-send`). Per-conversation fallback order —
the chain order is global (`providers.yaml`'s `fallback:` key); per-conversation needs a column,
a PATCH field and a control, and a column nothing writes is a reserved slot. **My Day round-tripping** — proven
impossible through this API, see the limitations note above.

## Ground rules

- **No half-built features.** No reserved enum slots, no schema for code that doesn't exist, no
  docs for unbuilt things. No code path → doesn't go in.
- **Verify the path completes, not that code is wired.** Real bugs found only by running flows
  (MCP tools "sold" before any request; confirmation never waking the turn; "don't ask again"
  wrote a key the gate never reads; empty/truncated reply ended turns).
- **Mutation-check regression tests** — reintroduce bug, confirm test fails.
- **Tests must not read the dev machine.** `conftest.py` isolates `PSOK_HOME` + in-memory keyring
  (keyring leak: a full `pytest` once deleted a real GitHub token). Any new store gets same treatment.
- **Fuller audit 2026-08-27:** Gmail "Connection closed", turn-latency with numbers, cold automation
  stall, interface needs. Corrects some claims above. See
  [AUDIT-2026-08-27.md](AUDIT-2026-08-27.md).

**Read this before starting; update before ending.** Exists so state isn't re-derived from git log
each time. Stale → fix in place.
