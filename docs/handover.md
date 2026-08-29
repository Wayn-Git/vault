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

**Verified:** 507 unit tests, `ruff` clean, 53-check Playwright suite (`frontend/tests/smoke.mjs`)
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
- **The OAuth app is stuck in *Testing*, and publishing is blocked (tried 2026-08-29).** A
  Testing app's consent expires **seven days** after it is given — the credential file
  `~/.google_workspace_mcp/credentials/<address>.json`, last written 2026-08-26, was three days
  from dying. That expiry, not a PSOK bug, is what "Google signed itself out again" is.
  Publishing to production would end it, but **Publish app refuses**, verbatim: *"Your app's
  OAuth configuration is incomplete. You must enter the missing information to proceed. Please
  visit the Branding page to finish configuring your app."* Google's own help pages describe
  the home page / privacy policy / terms fields as *verification* requirements and the console
  marks none of them with a required asterisk — the console enforces them at publish anyway,
  which is worth knowing before anyone re-reads the docs and concludes otherwise. The fields
  cannot simply be filled: each URL must sit on an **Authorized domain**, which needs Search
  Console ownership, and `*.vercel.app` and `*.github.io` are public suffixes that cannot be
  verified. Unblocking this starts with buying a domain. Until then: test-user sign-in, renewed
  weekly.
- **Groq is the default provider (2026-08-29)**, `openai/gpt-oss-120b`, with NVIDIA behind it
  in the chain. `/api/health` now lists providers in **providers.yaml order** rather than
  alphabetically — the interface takes the first entry as the house default, so sorting made
  that an accident of spelling. Two things found by running it: Groq **refuses more than 128
  tool schemas** (`400 'tools' : maximum number of items is 128`), now declared as `max_tools`
  and trimmed by the director with one warning naming what was withheld; and Groq's free tier is
  **8,000 tokens per minute**, which 178 tool schemas (11,582 tokens) exceed on their own — so a
  turn falls back to NVIDIA until connectors are switched off. Measured cost per connector:
  github 3,007 · chrome-devtools 1,771 · linkedin 1,456 · gmail 1,449 · playwright 1,206 ·
  builtins 983 · to-do 952 · calendar 654 · fetch 104.
- **Only Gmail scopes were ever granted.** The credential file lists `openid`,
  `userinfo.email/profile` and six `gmail.*` — no Calendar, Drive, Docs or Sheets, while
  `GOOGLE_MERGED_TOOLS` names five services. A merged connector would register tools for four
  services the token cannot call. Add the scopes under Data Access before re-consenting.
- **`google-docs`, `google-drive`, `google-sheets` removed 2026-08-29** — all three were
  `failed / not running` and the grant has no scopes for them. `psok mcp remove` only clears
  PSOK's own keychain entry, so the shared `~/.google_workspace_mcp/credentials` was untouched
  and Gmail stayed signed in. `merge-google --apply` was **not** run: its dry run merges all five
  services into one process, which would register drive/docs/sheets tools that 403 on first call.
- **The second Google account was signed out 2026-08-29.** Two addresses sat in the shared
  credentials directory and `MCP_SINGLE_USER_MODE` picks one, which nothing could report — the
  connector row now says when a store holds more than one. `ejramwayne@gmail.com.json` was moved
  to `~/.psok/signed-out-accounts/` rather than deleted.
- **Vercel, MS To Do, LinkedIn, Spotify** added + started before shipping. Vercel accepts
  dynamic registration (201) — nothing to register by hand. To Do returns device code. LinkedIn
  19 tools, Spotify 22 (needs a Spotify dev app).
- **Refused:** WhatsApp servers all need `better-sqlite3` (Node 20–25; this box runs **Node 26**
  → exit 1) — recheck when it ships 26 support. `jordanburke/microsoft-todo-mcp-server` broken in
  all 5 versions; `fabienbutz/microsoft-todo-mcp` shipped instead (uses Microsoft's public client).
- **Tests:** `pytest` (507 unit, 1 skipped), `pytest -m live` (5), `ruff check psok tests`.
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
- **Connected ≠ signed in.** A Google connector that never finished OAuth still registered 15
  Gmail tools; the model called one, got `Connection closed`, invented an outage and gave up.
  Tools of an unsigned connector are now withheld and the failure is an instruction (2026-08-28).

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

## Remaining work — phases 3 to 5, all done

Phases 1 (tasks + To Do) and 2 (turns that resolve, Stop) are **done and
live-verified 2026-08-27**; phases 3 (providers and fallback), 4
(connector setup) and 5 (modes and status) are **done and live-verified
2026-08-28**. Every numbered phase in this document is now built. What follows is written for whoever picks this up.
Order is payoff order; each phase is independently shippable and has its own
verification. Do not start the next until the current one's checks pass.

Context and measurements: [audit-2026-08-27.md](audit-2026-08-27.md),
[architecture/tasks.md](architecture/tasks.md),
[architecture/turns.md](architecture/turns.md),
[architecture/providers.md](architecture/providers.md),
[architecture/connectors.md](architecture/connectors.md),
[architecture/modes.md](architecture/modes.md).

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

**Per-conversation fallback order is built**: a `fallback` column on
`conversations`, set through `PATCH /api/conversations/{id}`, overriding
providers.yaml's `fallback:` key and then its own order. `[]` means "do not fall
back here" and is distinct from unset. **Left undone:** a control in the
interface for it — the column and the route are tested; nothing in the UI sets
them yet.

### Phase 4 — connector setup that finishes itself — **DONE, verified 2026-08-28**

Full write-up: [architecture/connectors.md](architecture/connectors.md). The
latency half was already done (2026-08-27, >115s → 3.9s); this is the experience.

- **4.1 Tools of a connector nobody signed in to are withheld.**
  `psok/mcp/guidance.py` asks `is_signed_in` — the server's *own* store, not the
  keychain — and unions the result into the `hidden_servers` the director already
  passed to `registry.schemas()`. `None` (nothing to sign in to) is not `False`,
  so the fetch connector is untouched. `dispatch` refuses too, because a model
  can name a tool it saw last turn. Cached 5s; `forget()` runs on every sign-in,
  toggle and connect, so a fix is believed immediately. **This is the original
  reported bug.**
- **4.2 A connector failure is now an instruction.** Names the connector, the
  screen, the button, and says **not to retry** — retrying is what spent the
  iteration budget. One module holds the wording so three call sites cannot
  describe three interfaces. An `OAuthRequired` no longer answers `psok mcp
  login` at someone sitting in a browser.
- **4.3 One state per connector.** `psok/mcp/lifecycle.py`:
  `off / starting / setup / authenticating / sign_in / syncing / failed / ready`,
  each with the single `action` that moves it on. Computed on the server and
  shipped on every `GET /api/mcp/servers` row as `lifecycle`, so the screen, the
  CLI and the loop cannot disagree. The order of the checks is the design — a
  connector mid sign-in is *authenticating*, not "not connected". `starting` is
  no longer indistinguishable from `failed`; missing credentials are named, not
  counted; `microsoft-todo` is not `ready` until its first pull. **Adding a
  connector now switches it on, starts it and returns that state** — still
  non-interactive, because a browser opening behind someone who pressed Add is
  the mistake Phase 4 exists to stop.
- **4.4 The five Google connectors can be collapsed into one.**
  `psok mcp merge-google`, dry by default, `--apply` to act. Backs up `mcp.yaml`
  first, grants only the services actually configured, carries the capability
  rows and clears the stale ones. The catalogue also offers `google-workspace`
  directly now, so a fresh install cannot recreate the problem. **The sign-in
  survives** — every entry points at the same
  `~/.google_workspace_mcp/credentials`.
  **Not applied to this machine.** The dry run against the real config reports 5
  sources, the right tool list and `signed in: yes`; running it is the account
  owner's call, which is what "do it deliberately" asked for.

**Verified** as this section asked, against a real stdio MCP server and a real
unauthorised OAuth connector with the keychain isolated: cold `connect_all` took
**0.0s** with `github` reported rather than waited on, the working connector
reached `ready` in one step, its tools were withheld from the model (`offered:
[]`) and came straight back on sign-in. Live `psok serve`: adding a connector
returned `lifecycle` naming the two credentials it still needed; a no-auth one
returned `ready`. 20 new tests, 477 in the suite.

### Phase 5 — two real modes, and a system that says what it is doing — **DONE, verified 2026-08-28**

Full write-up: [architecture/modes.md](architecture/modes.md).

- **5.1 Plan mode is a mode now, not a sentence.** `TurnRequest.mode`
  (`chat`|`plan`, 400 on anything else, before the stream opens); `Director`
  takes it. The instruction goes on the **system prompt**, so it is no longer
  persisted into the transcript and replayed forever. Mutating tools are
  withheld by `registry.schemas(read_only=True)` and refused at `dispatch` —
  gated on `RiskLevel.LOW`, which already means "changes nothing", so a
  connector's tools are covered the day it is added. The refusal runs **before**
  the permission gate: a plan turn must not raise a confirmation prompt either.
  The plan comes back as a `submit_plan` tool call (offered only in plan mode,
  never registered, intercepted by the director) → a `plan` frame the UI renders
  as steps with **Approve and run** / **Discard**. Approval is an ordinary chat
  turn; the plan is persisted as the assistant's own words, which is what the
  executing turn reads.
- **5.2 `status` frames.** Closed vocabulary in `director.STATUSES`:
  `retrieving · recalling · thinking · planning · generating · tool · connector ·
  retrying · switching · completed · cancelled · failed`. The composer said
  "Thinking" from the moment a turn opened until the first token, whatever the
  wait actually was; it now says which, and names the tool or connector.
- **5.3 A turn-cost line.** `done` carries `steps`/`tools`/`duration_ms`;
  rendered as `2 steps · 1 tool · 57ms`. `execution_logs.duration_ms` had held
  half of this since logging shipped with nothing reading it.
- **5.4 Unknown frames are logged**, not dropped by `default: break`.

**Verified** as this section asked — same request in both modes against a real
HTTP provider and a real file on disk, with the model trying to write in *both*:
chat answered in one pass and the file was written (`2 steps · 1 tools · 57ms`);
plan returned a two-step list, **wrote nothing**, and offered 12 tools with
`write_file` and `run_shell_command` absent; a `write_file` with
`read_only=True` was refused **by the registry** while `list_files` still ran.
18 tests for this phase, 503 in the suite.

**`step_started`/`step_done` are built**, from the model's own `begin_step`
calls — offered only on a turn carrying out a plan, answered by the director,
never inferred from which tools ran. A step closes when the next opens or the
turn ends; a model that ignores the tool produces no events rather than guessed
ones. Plan steps are **editable** before approving, and an edited plan travels
with the approval.

**Left undone on purpose:** `syncing` as a *turn* state (nothing in a turn syncs;
it is a connector state — a name in `STATUSES` nothing emits would be a reserved
slot, and a test now fails if one appears), and adding or reordering plan steps.

### Known limitations, proven not assumed (2026-08-27)

Both were checked against the real account, not the API docs. Neither is a PSOK
bug and neither has a fix from this side:

- **To Do's own My Day is not in its API — but My Day now syncs anyway.**
  Re-verified against the live account 2026-08-28, harder than before:
  `$select=showInMyDay` and `isInMyDay` both return
  `400 Could not find a property named ... on type 'microsoft.graph.todoTask'`
  on **v1.0 and beta**; the live `beta/$metadata` lists twenty-one `todoTask`
  properties and **none contains "day"**; there is no `myDay` well-known list
  (only `defaultList`, `flaggedEmails`, `none`); the legacy `/me/outlook/tasks`
  surface is alive and has no such field either; and every MAPI
  extended-property probe came back empty. Four independent routes, all closed.

  **The category was tried and removed. My Day is a list now (2026-08-29).**
  `categories` round-trips, so the sun wrote a `My Day` tag — and it still did
  not work, for a reason only the live account showed: today's tasks are added
  through **To Do's own My Day**, the overlay at the top of its sidebar, and
  those carry no tag, no hashtag and no list. Measured 2026-08-29: the two tasks
  ever put in the user's own My Day *list* synced correctly; the six added that
  morning through the built-in My Day came back filed in `Tasks`. So My Day is
  now one ordinary list — named in `MY_DAY_LIST_NAMES`, matched past a leading
  emoji — and the bucket is `list_id = :my_day_list`. `my_day_on`, the category
  and the `#myday` hashtag are all gone; the column is dropped by a migration.
  The sun **moves** the task, and Graph has no move, so that is a create in the
  target plus a delete from the source: the task gets a new id, loses its
  checklist, and the local row does not move at all if either half fails. The
  cost is stated on the page: a task in My Day has left the list it came from,
  and tasks added to To Do's *own* My Day remain unreachable — nothing can fix
  that from here.
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

## What changed 2026-08-29

Seven complaints, all measured before being acted on:

1. **My Day is a list.** See the limitations note above and
   [architecture/tasks.md](architecture/tasks.md).
2. **133 conversations deleted**, keeping the newest hand-typed one. Backup at
   `~/.psok/psok.db.backup-before-conv-purge-*`.
3. **Read-only connector tools stopped asking permission** — 85 of 178 tools now run silently.
4. **The screen keeps up**: health polls every 8s (was 20s), and the Connectors page refetches
   `/api/mcp/servers` on its existing 3s ticker while the tab is visible, so a connector that dies
   is reported without a reload. It stops polling on a hidden tab.
5. **Sync every 90 seconds** (was 900), lists pulled **concurrently**, and the Tasks page asks for
   one when it opens.
6. **Groq is the default model**, with the tool cap and quota findings above.
7. **A Mail view** (`⌘3`), reading Gmail directly.

8. **Three model tiers and a reasoning mode** (2026-08-29, later the same day). `providers.yaml`
   gained a `tiers:` block — `fast` groq/gpt-oss-20b (0.50s), `default` groq/gpt-oss-120b
   (0.60s), `heavy` nvidia/deepseek-v4-pro (112.6s). A tier answers "how hard is this work";
   the fallback chain answers "who else, when this one is down", and conflating them would make
   a quota trip look like a decision. `reasoning` joins `chat` and `plan` as a mode and starts
   on `heavy`. The fast model can hand a job over with an **`escalate` tool** — offered, never
   registered, answered by the director, exactly like `submit_plan` — which ends the turn with
   an `escalation` frame the user answers. Not a classifier (a round trip on every message) and
   not a heuristic (guesses silently): the model is the only party that knows it is out of its
   depth. Withheld when no `heavy` tier resolves, and never twice in a row.
9. **`convert_file`** — images, audio, video, documents and PDF, through ffmpeg, ImageMagick,
   LibreOffice, ghostscript and pandoc, all on this machine. Not ConvertAPI (it uploads personal
   documents, against ADR-0013) and not VERT (a Svelte app running those same three engines in
   WebAssembly, so a browser and a wasm layer to reach binaries on `PATH`). Verified on real
   files: png→jpg, wav→mp3, docx→pdf, pdf→png, each checked with `file` afterwards.
10. **The system prompt stopped asking for demonstrations.** "Can you make tool calls?" took
    **55s, 6 steps and 5 tool calls** — it listed the repo, read two SKILL.md files and shelled
    out to `date` while the date sat in the `<environment>` block it had been handed.
    `BASE_PROMPT` said "prefer acting" with nothing on the other side of the scale; it now says
    to match the work to the question, and that `<environment>` is authoritative.

Plus, found by running it: `google-docs/drive/sheets` removed, the second Google account signed
out, a sign-in with a known shelf life now says how long it has left, and Groq's `reasoning` field
(as opposed to NVIDIA's `reasoning_content`) is read rather than dropped.

**The lever nobody has pulled:** 178 tools cost 11,582 tokens of schema on *every* round trip, and
Groq's free tier is 8,000 tokens a minute — so the fast provider cannot be used until the tool
surface shrinks. `github` (3,007) + `chrome-devtools` (1,771) + `linkedin` (1,456) +
`playwright` (1,206) is 7,440 of it. Switching those off leaves 62 tools at 4,142 tokens, which
fits, and gives the model a surface it can actually choose from. Nothing in code decides this: it
is four switches in Skills & connectors.

## Next steps (roughly in payoff order)

0. **Google sign-in expires weekly and there is no cheap fix.** Publishing is blocked (see
   Environment facts); a domain, three hosted pages and a Search Console verification are the
   price of ending it. Meanwhile the grant has to be renewed roughly every seven days: sign out
   of the Google connector, sign in again. Add the Calendar/Drive/Docs/Sheets scopes under Data
   Access first if those connectors are wanted — only Gmail was ever granted. Preflight passes,
   URL published with TTL, `8765` held.
1. **`nvidia/nemotron-3-ultra-550b-a55b` is dead** — listed by `/v1/models` but 404s with an
   empty body on `chat/completions`, while `nemotron-3-super-120b-a12b` and
   `nemotron-3-nano-30b-a3b` answer fine. Default switched and 130 conversations repointed
   2026-08-28. A model can vanish from a tier without leaving the catalogue.
2. **Rotate NVIDIA key + Google secret** (both touched a transcript). Highest-consequence loose end.
3. **Verify Anthropic/OpenAI live** once a key exists — most likely place for a real defect
   (only path never exercised for real). Now `psok providers add anthropic` + `psok secrets set
   psok/anthropic`, or Settings > Models.
4. **Bring Ollama up + one real indexing pass** — closes default-embedding gap.
5. **GitHub connector** — register app + re-enable only if wanted; absent beats permanently-failing.
5. **Run `psok mcp merge-google --apply`** when convenient — collapses the 5 Google connectors
   into one process, keeps the sign-in, backs up `mcp.yaml`. Dry-run verified against this
   machine's config; deliberately not applied for you.
6. **Decide** first-party Gmail/Calendar/Drive vs connector path. Open: does data need *local sync*
   to cross-reference with the vault, or is on-demand enough? (unresolved on purpose)
7. ~~Automation~~ **Built (beta)** — runs while `psok serve` is open; unattended gate denies +
   records blocked ops. Missing on purpose: cron, non-clock triggers, retries. See
   [architecture/automation.md](architecture/automation.md).
8. **Recurring tasks + background jobs** — two capabilities most implied by "personal OS" that
   aren't built; neither has a design. Real design work, not a quick add. Note Graph *does*
   expose `recurrence` on a task and PSOK never requests it, so the To Do half is readable
   whenever someone designs the local half.
9. ~~Conversation delete~~ **Built.** `DELETE /api/conversations/{id}` (409 while turn streams),
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
| Streamed turn | `POST /api/conversations/{id}/turn` `{message, workspace?, mode?}` → SSE (mode `chat`\|`plan`\|`reasoning`, 400 otherwise) |
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
| Who mail reads as | `GET /api/mail/account` (never raises: answers `address: null` when nobody is signed in) |
| Mail list / one thread | `GET /api/mail/threads?q=&limit=`, `GET /api/mail/threads/{id}` (409 when signed out) |
| Reply in thread | `POST /api/mail/threads/{id}/reply` `{body}` |
| Label / archive a message | `POST /api/mail/messages/{id}/labels` `{add, remove}` — archiving is removing `INBOX` |
| Gmail labels | `GET /api/mail/labels` |
| Add/change/cancel task | `POST /api/tasks`, `PATCH,DELETE /api/tasks/{id}` (writes to MS To Do when connected) |
| Abandon sign-in | `DELETE /api/mcp/servers/{name}/login` |
| Pull To Do now | `POST /api/tasks/sync` |
| Connector catalogue | `GET /api/mcp/catalogue` |
| Configured connectors | `GET /api/mcp/servers` (each row carries `lifecycle`: state/detail/action/ready) |
| Add/remove connector | `POST,DELETE /api/mcp/servers` (POST switches on, starts, returns `lifecycle`) |
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
- `status {state, tool?, server?}` — named state, closed set (`retrieving`/`recalling`/`thinking`/
  `planning`/`generating`/`tool`/`connector`/`retrying`/`switching`/`completed`/`cancelled`/`failed`)
- `plan {summary, steps[]}` — plan mode's answer; render with Approve / Discard, nothing has run
- `escalation {reason, from_model, to_model}` — the fast model asking for the heavy one. Turn is
  over and nothing ran: render Escalate / Answer anyway, both of which **re-send the same
  message**, in `reasoning` mode and `chat` mode respectively. No resume endpoint and no flag —
  the backend withholds the tool because the transcript records the request.
- `warning {message}` — stream cut off / turn continuing an empty reply / **provider fell back**
  (*"nvidia was unreachable — answering with groq/llama-3.3-70b instead"*, one line, not terminal)
- `guard {reason}` — loop limit / user stop
- `error {message}` — always last
- `done {text, iterations, steps, tools, duration_ms}` — last three are the turn-cost line
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

**A connector's tools are no longer all `MEDIUM` (2026-08-29).** They were, on the reasoning that
PSOK cannot inspect somebody else's server — and with 156 of 178 tools coming from connectors,
every search and every list raised a prompt, which is how a gate stops being read. It can inspect
them: MCP carries `readOnlyHint` and `destructiveHint` on every tool and discovery was discarding
the field. `psok/mcp/risk.py` reads it, falls back to the verb the name starts with for servers
that annotate nothing, and never *lowers* a declaration — a server calling `delete_everything`
read-only is wrong or lying. Live result on this machine: **85 low, 59 medium, 34 high** where it
had been 156 medium.

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
   itself signed in). **Since 2026-08-28** every row carries a server-computed `lifecycle`
   (`off/starting/setup/authenticating/sign_in/syncing/failed/ready`) and offers the one button
   its `action` names; grouping and labels read that rather than re-deriving from five fields.
   A connector running with no account has its tools **withheld from the model** — see
   [architecture/connectors.md](architecture/connectors.md).
7. **Audit/permissions/memory** — trail w/ follow mode; standing approvals w/ revoke
   (Settings→Permissions); facts w/ switch + retire.
8. **Attachments** — drop/paste/pick (`⌘U`) → `~/.psok/attachments/<id>/<name>`, message carries path.
9. **Modes: chat / plan / reasoning** — a three-way composer toggle, not a boolean.
   `reasoning` starts on the `heavy` tier, and is what Escalate on an escalation card sends.
   **Plan mode** — sending `mode: "plan"`. Mutating tools are **withheld by the
   registry** and refused at dispatch, so a write is impossible rather than discouraged; the
   model hands back `submit_plan` and the UI renders steps with Approve and run / Discard.
   Approval is an ordinary chat turn. The instruction lives on the system prompt, so it is no
   longer persisted or replayed. See [architecture/modes.md](architecture/modes.md).
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
    state, **except My Day, which is a list** (2026-08-29): the To Do list called `My Day`
    *is* the bucket, the sun moves a task in or out of it, and the rail does not show it
    twice. To Do's own My Day is still unreachable — anything added there is invisible here.
    See [architecture/tasks.md](architecture/tasks.md).
13. **Mail** (`⌘3`, new 2026-08-29) — inbox / unread / starred / sent / all, Gmail search syntax,
    a thread reader, star, mark read, archive and a plain-text reply. Read **straight from Gmail**,
    not through the connector: `search_gmail_messages` answers in prose written for a model
    (`📧 MESSAGES:`, `Message ID:`), and a screen built on that is a regular expression over
    somebody else's help text. `psok/mail/gmail.py` uses the refresh token the connector already
    stored, reads that file and never writes it. HTML mail is reduced to text **on the server** —
    an inbox is the most hostile input this system has, and a view that renders what arrives in it
    is a different feature with a different threat model. The page says when a message was reduced.
14. **Settings→Models** — writes `providers.yaml` rather than describing it. Configured rows carry
    `ready` / `needs a key` / `not answering`; the rest of the 13-entry catalogue is one Add each,
    plus a row for any OpenAI-compatible endpoint. Key goes to the keychain and no route hands one
    back. Remove drops the entry and **keeps the key** (`psok secrets delete` is the other decision).
15. **Settings→Data** — clear convs or facts, each behind 2-click confirm + count first. Tasks,
    audit, index, creds untouched.
16. **Pins** — header pin or `⌘P`; strip above transcript. Deliberately inert (not sent to model,
    no recall effect). Column on `messages`; streaming msg can't pin until read back.

## Deliberately not built

Projects/artifacts/plugins/voice/"cowork" (nothing backs them; absent > dead row). Screenshot from
composer (no portable Linux w/o compositor; Playwright covers the real case). Extended-thinking
toggles (absorbed in adapters). Pins-that-mean-something (would be a different feature). Anything
multi-user (ADR-0001). Automations answering permission prompts (deny + report). Recurring tasks
(no schema slot; reminders ≠ recurrence). Two-way task sync — **built 2026-08-27**, My Day included **2026-08-28**, My Day rebuilt as a
list **2026-08-29** (`dirty_at` push-then-pull avoids merge algo; lists mirrored; vanished tasks
stay `cancelled` not deleted). A `My Day` category and a `#myday` hashtag both existed and were
**removed**: a task added through To Do's own My Day carries neither, so they named a different
set of tasks than the phone did.
Per-step progress events (`step_started`/`step_done`) — they need the executing model to announce
step boundaries, a second protocol; without one the interface would invent which step it is on.
Editing a plan in place (Discard is local; change the request and plan again). A classifier that
picks chat vs plan (a round trip on every message; the toggle is one click).
Notification delivery guarantees (best-effort `notify-send`). A UI control for the per-conversation
fallback chain (the column and the PATCH field exist and are tested; nothing sets them from the
screen yet). Adding or reordering plan steps (titles are editable; adding one the model never
proposed is writing a plan, not approving one). **Reading To Do's own My Day** — proven
impossible through this API, see the limitations note above; a list called My Day is what works
instead.

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
  [audit-2026-08-27.md](audit-2026-08-27.md).

**Read this before starting; update before ending.** Exists so state isn't re-derived from git log
each time. Stale → fix in place.
