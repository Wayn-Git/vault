# Session state — 21 August 2026

Working notes for picking this up again. Everything below is uncommitted: the
tree is 42 modified files plus 3 new ones, on top of `009587c`.

---

## Where it stands right now

| | |
|---|---|
| Backend | `uvicorn psok.api.main:app --port 8000`, running against the real `~/.psok` |
| Frontend | Vite dev on `:5173` — open **http://127.0.0.1:5173** |
| Tests | 225 unit passing (1 skipped: sandbox case), 5 live MCP passing, `ruff` clean |
| Frontend checks | `npm run build` and `oxlint` clean. **No frontend test suite exists.** |
| Default model | `nvidia/nemotron-3-ultra-550b-a55b` |

Both servers were started for testing. `pkill -f "uvicorn psok"` stops the API;
the Vite server was already yours.

### Changes made to the machine, not just the repo

- `~/.psok/config/providers.yaml` — added an `nvidia` entry pointing at
  `integrate.api.nvidia.com`, resolving the key already in the keychain at
  `psok/nvidia`. Backup: `providers.yaml.bak`.
- `~/.psok/psok.db` — migrated in place (it predated the current schema and the
  API would not start against it). Backup: `psok.db.backup-20260821`.
- `~/.psok/config/mcp.yaml` — `github` and `google-workspace` added. Both are
  **switched off**; nothing spawns until they are turned on.
- The database still carries three empty tables from the abandoned earlier
  version — `credentials`, `integrations`, `integration_state`. Left alone
  deliberately. Say the word to drop them.

**The NVIDIA key is worth rotating.** `docs/NEXT-SESSION.md` records that it was
pasted into a shell and a transcript.

---

## What was implemented

### 1. Audit fixes — existing features that did not work

Found by tracing documented behaviour against the code, then by running it.

- **The OpenAI-compatible adapter sent PSOK's own message rows as the wire
  format.** Replayed tool calls carried no `"type": "function"` and an
  `arguments` object rather than a JSON string, plus PSOK's internal
  `tool_name`/`is_error` columns. One-iteration turns hid it; the second request
  of every tool-using turn would 400 against a strict server. The other two
  adapters already translated. `psok/runtime/providers/openai_compat.py`.
- **A provider that ignores `stream: true` produced a silent blank turn.** No SSE
  frames meant the adapter yielded an empty response, and the loop ended with no
  answer, no tool call, no warning. Both streaming adapters now re-ask without
  streaming when a stream carries nothing.
- **The loop treated "took the streaming path" as "already showed the answer"**,
  so a fallback answer emitted no `assistant_text` and the interface had nothing
  it was allowed to render.
- **Documented retrieval injection was never wired.** `SearchService.context_for`
  was written, tested, referenced in two docs, and called by nothing. Now
  pre-fetched once per turn, skipped entirely on an empty index.
- **`edit_file` did not invalidate the document index**, though `write_file` and
  `delete_file` did and the indexer's docstring named it.
- **Per-conversation connector toggles did nothing.** State was stored and never
  applied. Now withheld from the tool schemas and refused at dispatch.
- **Switching a connector on never reached the running API.** Added
  `MCPManager.reconcile()`, run at the start of each turn;
  `POST /api/mcp/servers/{name}/connect` now connects into the live registry
  instead of a throwaway manager it immediately discarded.
- **"Don't ask again" keyed a sandbox that wasn't one.** Where no sandbox backend
  exists, sandbox-mode shell commands run uncontained but keyed as `:sandbox`.
  They key as `:direct` now.
- `psok capabilities --kind plugin` crashed on a dead enum slot; reasoning from
  non-streaming providers was dropped; one `ruff` error.

### 2. Long-term memory (Phase 9)

The store and service existed from an earlier session and nothing reached them.
Now wired end to end, and the phase's acceptance criterion holds: a fact stated
in one conversation is recalled, unprompted, in a later separate one.

- Recall runs before prompt assembly; extraction runs **after** the `done` event,
  because it is a second model call and blocking the terminal event on it would
  keep the composer disabled for its duration. A `memory` frame follows when
  something changed.
- Extraction model: `memory:` in `providers.yaml` names a small local one;
  without it, the conversation's own model is used.
- Duplicates are refused at the store, not merely discouraged in the prompt.
- `GET /api/memory`, `POST /api/memory/toggle`, `DELETE /api/memory/{id}`,
  `psok memory [--forget ID] [--on|--off] [--conversation ID]`.
- 20 tests in `tests/test_memory.py`, each mutation-checked.

### 3. Turn interruption

The UI had a Stop button that aborted the browser's read while the loop kept
calling models and tools — and a call suspended on a confirmation held the gate
for its six-hour timeout with nobody left to answer.

`POST /api/conversations/{id}/turn/stop` sets an event the loop reads before its
next model call and while a dispatch is in flight. The in-flight call is
cancelled and recorded as interrupted, and the turn ends with a `guard` frame.
This is the interruption `docs/architecture/ai-runtime.md` always described and
nothing implemented.

### 4. Database migration

**The backend would not start against any pre-existing database.**
`schema.sql` is written with `CREATE TABLE IF NOT EXISTS`, which silently skips a
table that already exists in an older shape — then the index over its new column
fails with a bare `no such column: superseded_at`.

`migrate()` now compares each existing table against a throwaway database built
from `schema.sql` itself and adds missing columns before applying it, so there is
no second list of columns to keep in step. A column it cannot add (NOT NULL, no
default) is logged by name rather than failing opaquely.

### 5. Frontend revamp

Composer-first, in the shape of the reference screenshot.

- Empty state is a centred editorial hero and one field. Everything else hangs
  off the `+` menu beside the composer: Skills ▸, Connectors ▸, Memory (toggle),
  Workspace ▸, activity. Each row is live state — the counts are what is actually
  switched on, and toggles write at conversation scope when a conversation exists
  and global scope before one does. `CapabilitiesPanel.jsx` was deleted; the menu
  supersedes it.
- Design language: warm near-black canvas, one desaturated clay accent,
  Instrument Serif for display / Geist for UI / Geist Mono for metadata,
  double-bezel construction on the composer and cards, hairline borders, no drop
  shadows beyond one diffuse lift, every transition on
  `cubic-bezier(0.16, 1, 0.3, 1)`, `prefers-reduced-motion` honoured. The rail
  became a slim top bar.
- Confirmations are event-driven off the `confirmation_required` frame rather
  than polled, and the modal now shows the `operation_key` a "remember" would be
  stored under — it previously hid it and wrongly refused to remember high-risk
  decisions.
- New Memory view; connector on/off switches in the MCP view; provider and model
  switched from the composer chip; connector failures surfaced in chat and on the
  status view.
- `/api/health` gained `provider_defaults` so the composer prefills the model
  `providers.yaml` already declares.

### 6. Connector credentials in the environment

A stdio server that takes credentials through its environment had nowhere to put
them but `mcp.yaml`, breaking PSOK's rule that secrets only ever exist in the
keychain. An `env` value of `keychain:<ref>` is now resolved at spawn time, and
`psok mcp env <server> KEY=VALUE --secret` writes both halves.

While checking the Google server's actual contract, two errors in PSOK's own
catalogue entry were corrected: it said **Desktop** OAuth client where that
server requires a **Web application** one, and its callback defaults to port
8000 — where the PSOK API runs. The entry now pins `WORKSPACE_MCP_PORT=8765`.

---

## Second pass — the shadow-state fix and the interface

### The connector switch reported intent, not fact

Switching a connector on wrote a capability row and left connecting until the
next turn. The row then read "on" whether the process had started, had died, or
had never been asked to start, which is why connectors looked enabled while the
agent had none of their tools.

- `POST /api/capabilities/connector/{name}` now starts or stops the process and
  waits for the outcome, answering with `{connected, tools, error}`.
- `GET /api/capabilities` carries the same live block on every connector row.
- `MCPManager.state()` is the single source of that truth.
- A server removed from `mcp.yaml` no longer leaves its failure behind, which
  used to keep `/api/health` degraded over a connector that no longer existed.
- Verified against the real thing: playwright reports 24 tools about three
  seconds after the switch, a server whose binary is missing reports
  `FileNotFoundError` on its row instead of reading "on", and a turn driven
  through Vite's proxy actually calls `fetch__mcp__fetch`.

### Interface, second revision

Type is Bricolage Grotesque / Schibsted Grotesk / JetBrains Mono. The palette is
cool graphite and **colour is reserved for liveness and risk** — a connector
that is actually running is mint, a confirmation is amber, a stop is coral, and
nothing else on the screen carries chroma.

The signature is the **armed strip** under the composer: what the agent can
reach right now, with real state per connector. Clicking a chip starts or stops
that process and the chip changes only when the process does.

Motion follows Emil Kowalski's framework: custom curves, nothing over 300ms,
`scale(0.97)` on press, popovers scaling from their trigger, transitions rather
than keyframes for anything re-triggerable, hover behind
`(hover: hover)`, reduced motion respected. GSAP is gone — CSS animations run
off the main thread, which matters while a turn is streaming. Bundle went from
323KB to 251KB (103KB to 76KB gzipped).

Checked by driving PSOK's own Playwright connector against its own interface and
reading the screenshots: home, the + menu, a conversation, connectors, activity,
memory, and a 430px viewport. That pass caught and fixed a stranded hero, an
audit table whose rows stretched to several hundred pixels, invented timestamps
on the status panel, and three places where colour was decoration.

## Not done yet — pick up here

### GitHub auth (~5 min, browser work is yours)

1. [github.com/settings/developers](https://github.com/settings/developers) →
   **New OAuth App**
   - Application name: `PSOK`
   - Homepage URL: `http://127.0.0.1:5173`
   - **Authorization callback URL: `http://127.0.0.1:33418/oauth/callback`** —
     must match exactly; it is the loopback listener PSOK opens
   - Generate a client secret
2. `psok mcp auth github --client-id <id> --client-secret <secret>`
3. `psok mcp login github` — opens GitHub's real login page
4. Switch it on: `+` → Connectors → GitHub, or
   `psok capabilities --enable github`

Expect two prompts on first use: the OAuth sign-in, then the one-time MCP server
trust confirmation.

### Gmail auth (~15 min)

1. [console.cloud.google.com](https://console.cloud.google.com) — create or pick
   a project
2. **APIs & Services → Library** → enable **Gmail API** (plus Calendar and Drive
   if wanted)
3. **OAuth consent screen** → External → add your own address under **Test
   users**. Without this Google refuses the sign-in.
4. **Credentials → Create OAuth client ID → Web application**
5. Authorised redirect URI, exactly:
   `http://localhost:8765/oauth2callback`
6. Store them:
   ```bash
   psok mcp env google-workspace GOOGLE_OAUTH_CLIENT_ID=<id>.apps.googleusercontent.com
   psok mcp env google-workspace GOOGLE_OAUTH_CLIENT_SECRET=<secret> --secret
   ```
7. Switch it on and ask it something; the first tool call opens Google's consent
   page.

Once both are done: drive each connector end to end and confirm their tools land
in the live registry (`GET /api/health` → `mcp_tools`).

---

## Known gaps

- **The React app has no tests.** Build and linter pass and the flows were driven
  against a live server, but nothing locks component behaviour down. This is the
  largest hole in the frontend work; it needs vitest + jsdom, which means new dev
  dependencies.
- **No filesystem watcher.** `data-model.md` names three index-consistency
  triggers; two exist. A stale document is marked but nothing re-indexes it
  without `psok index`.
- **Skills docs still promise things that do not exist**: `requires_tools`
  warnings, automatic install of a skill's script dependencies, hash-based
  seeding (the code skips seeding if the directory exists).
- **Pending confirmations are memory-only**, so an API restart drops them despite
  the six-hour timeout implying otherwise.
- **Anthropic and Google adapters have still never run against their real APIs.**
  `openai_compat` is now validated against a strict format checker; those two are
  not.
- Parallel read-only tool execution (ADR-0016 calls it an opt-in flag) does not
  exist.

---

## Suggested order next session

1. Finish the two auth flows above and verify both connectors live.
2. Decide on frontend tests — without them this revamp is one refactor away from
   silent breakage.
3. Then either Phase 11 integrations (only if Gmail/GitHub data needs syncing
   locally rather than being reachable over MCP) or the filesystem watcher, which
   is the last unimplemented piece of a phase already marked complete.
