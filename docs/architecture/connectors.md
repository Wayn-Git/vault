# Connectors: what is offered, what is said, and what state it is in

Built 2026-08-28. [mcp.md](mcp.md) is how a connector works; this is how its
*setup* works — what the model is allowed to see, what it is told when something
is missing, and how a person finds out what a connector still needs.

## The bug this started from

A Google connector that had never completed OAuth put fifteen Gmail tools in
front of the model. The model called one, got `Connection closed` back, decided
there was a service outage, and handed the work back to the user — who could see
Gmail working fine in their own browser.

Two mistakes, and only fixing both is a fix:

1. **`connected` was being used to mean `usable`.** A stdio server starts,
   answers `initialize` and registers its tools long before an account is
   attached to it. Seven consecutive tool calls failed at `0ms` across three
   connectors — a duration that proves the request never left the process.
2. **The failure was an exception string.** It named no connector, no screen and
   no button, so the model could neither act on it nor relay it. `BASE_PROMPT`
   saying "errors are information, not dead ends" is true and far too general to
   help once the call has already been made.

## Tools that cannot work are not offered

`psok/mcp/guidance.py` answers one question: which connectors are running with
no account attached. It asks `commands.is_signed_in`, which reads the server's
*own* credential store rather than PSOK's keychain — reading the wrong one is
what made a connector that had never seen a Google account report itself signed
in.

The three-valued answer matters. `is_signed_in` returns `None` where there is
nothing to sign in to, and `None` is not `False`: the fetch connector needs no
account and must not be hidden. Only an explicit `False` hides anything.

That set is unioned into the `hidden_servers` the director already passes to
`registry.schemas()` for conversation-scoped toggles — the mechanism existed,
auth state just was not feeding it. And, as with the toggle, withholding the
schema is not enough on its own: a model can name a tool it saw in an earlier
turn, so `dispatch` refuses it too.

The set is cached for five seconds, because `is_signed_in` globs a directory and
parses JSON while `dispatch` asks once per tool call. `guidance.forget()` clears
it, and `MCPManager.forget_error` — which already ran on every sign-in, toggle
and explicit connect — now calls it. A cached "not signed in" outliving the
sign-in is how a connector stays hidden after the user has fixed it.

## Failures are instructions

Every connector failure the model can see now names the connector, the screen,
the button, and says **not to retry**:

> `'google-gmail' is running but no account is signed in to it, so none of its
> tools can work yet. This is not an outage and not a bug: it is a setup step
> only the user can complete. Tell them to open Skills & connectors
> (Cmd/Ctrl+3), Connectors tab, open the 'google-gmail' row and press Connect.
> Do not retry this tool. Finish everything else the request needs and say
> plainly which part is waiting on that sign-in.`

"Do not retry" is load-bearing. Retrying is what turned one dead connector into
a turn that spent its whole iteration budget rediscovering the same failure.

The wording lives in one module so the tool result, the dispatch guard and the
manager cannot drift into describing three different interfaces. One message
also changed audience: an `OAuthRequired` used to answer `psok mcp login
<name>`, sending someone who is in a browser to a terminal for a button two
clicks away.

## One state per connector

`psok/mcp/lifecycle.py`. The Connectors tab used to show `enabled`,
`signed_in`, `missing_credentials`, an error string and a separate
pending-authorization poll, and leave the reader to work out from those five
whether anything more was needed. That is how a connector reporting 122 tools
live ended up beside a "Sign in" button.

```
Adding -> Setting up -> Authenticating -> Syncing -> Ready
                                       \-> Failed (reason + Retry)
```

| state | means | action |
|---|---|---|
| `off` | switched off | `connect` |
| `starting` | nothing has asked it to run yet | `connect` |
| `setup` | needs named credentials before sign-in can begin | `credentials` |
| `authenticating` | the user is with the provider | none — wait |
| `sign_in` | running, no account attached; tools withheld | `sign_in` |
| `syncing` | signed in, first pull has not run | `sync` |
| `failed` | with the reason, led by what to do about it | `retry` |
| `ready` | usable | none |

**The order of the checks is the design.** A connector mid sign-in is also not
connected and also has no account; reporting either at that moment tells someone
looking at a consent page that the thing they are doing is not happening. So the
deepest unmet requirement wins, not the first one found.

Three details worth keeping:

- **`starting` is not `failed`.** They rendered identically, so on a freshly
  booted server every connector looked broken.
- **Missing credentials are named, not counted.** "Needs 2 credentials" cannot
  be acted on without going to find out which two.
- **`microsoft-todo` is not ready until its first pull.** Signed in, tools live
  and an empty Tasks page reads as the sync being broken rather than as never
  having been asked to run. Asked of the mirrored rows rather than a flag, since
  a flag would survive the tasks being cleared and then claim a sync that no
  longer shows anywhere.

`ConnectorsTab` already polls `GET /api/mcp/authorizations` every three
seconds; the row is refetched once when a sign-in starts waiting and again when
it settles, which is what makes `authenticating` visible for its duration
without asking every connector who it is signed in as three seconds apart for
the whole wait.

It is computed on the server and shipped on every `GET /api/mcp/servers` row as
`lifecycle`, so the screen, the CLI and the agent loop cannot reach different
conclusions from the same five fields. `ConnectorsTab.jsx` reads it — its
grouping, its row label and which single button the row offers all key off
`lifecycle`, with the old derivation kept as a fallback.

## Adding a connector finishes what it can

`POST /api/mcp/servers` used to end at a row in `mcp.yaml`, so "add" meant
"add, then go and find the switch, then go and find Connect". It now switches
the connector on, starts it, and returns its `lifecycle` — the same vocabulary
the list behind the dialog uses.

It also runs the connector's **first sync** where it has one -- Microsoft To Do
mirrors into the local tasks table, and until that pull has happened the Tasks
page is empty while the connector reports itself ready, which reads as the sync
being broken rather than as never having been asked to run. Best-effort: right
after adding it, "not signed in yet" is the expected state on the way through,
not a reason to fail the add.

**Non-interactive, deliberately.** A browser opening behind someone who pressed
Add is the same mistake as the serial sign-in that cost an automation its whole
budget: a sign-in is a step the user takes when they are ready for it.

Verified live: adding `google-workspace` answered
`setup / "Needs GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET before it
can sign in"`, and adding a connector that needs nothing answered
`ready / "Ready, 2 tools."` — in the one call.

## Collapsing the Google connectors

`psok/mcp/migrations.py`, run by `psok mcp merge-google`.

Five entries, each `uvx workspace-mcp --single-user --tools <one service>`, over
one Google account: five processes sharing one OAuth client, one credentials
directory and one callback port. That sharing produced two of the traps in
NEXT-SESSION.md — `sign_out` deleting the CSRF store the other four were mid-flow
against, and a port race that `WORKSPACE_MCP_PORT_FALLBACK_COUNT: "0"` correctly
turns into a loud failure. One process told to serve five tool sets has neither,
and is what `workspace-mcp` was built for.

The catalogue now offers `google-workspace` directly, so a new install does not
recreate the problem; the migration is for one that already has.

**The sign-in survives** because every entry — merged or single — points at the
same `~/.google_workspace_mcp/credentials`, and the account files are never
touched. That is why this is safe, and the first thing to check if it ever
stops being true.

Safety properties, in the order they matter:

- **Nothing runs it but a person.** No startup hook, no upgrade step, no side
  effect of adding a connector. `psok mcp merge-google` prints the plan and
  changes nothing; `--apply` is a second, separate decision.
- **`mcp.yaml` is copied to a timestamped `.bak` before anything is written.**
- **Only the configured services are granted.** Merging three connectors must
  not silently hand the model five, so the tool list is built from what is
  there, in catalogue order so the command line is stable.
- **Capability rows are carried over and the stale ones cleared.** `reconcile`
  reads them, and a row for a connector no longer in `mcp.yaml` is what left
  `google-workspace` listed as an enabled connector that did not exist.
- **Running it twice is a no-op** and takes no backup.

## Verified

- 22 tests in `tests/test_connector_setup.py`; 503 in the suite; `ruff` clean;
  frontend lint and build clean.
- End to end against a **real stdio MCP server** (raw JSON-RPC, two tools) and a
  real unauthorised OAuth connector, with the keychain isolated the way
  `conftest.py` isolates it:
  - cold `connect_all(interactive=False)` took **0.0s** — `github` was reported,
    not waited on, with a message naming the screen and the button, while the
    working connector came up with its 2 tools;
  - the working connector reached `ready` in that one step; `github` reported
    `sign_in` and named its own next action;
  - its tools were withheld from the model (`offered: []`), naming one anyway
    returned the instruction, and signing in brought them straight back.
- Live `psok serve`: `POST /api/mcp/servers` returned a `lifecycle` naming the
  two credentials it still needed; a no-auth connector returned `ready`.
- **The stated verify criterion, run as a real automation**: `run_once` against
  a real HTTP model with `github` *and* `vercel` unauthorised reached the model
  in **0.1s**, both connectors refused by name with the screen and the button,
  `status=ok`. `RUN_TIMEOUT_SECONDS` is 300 and two unauthorised connectors used
  to be able to eat it.
- `psok mcp merge-google` dry-run against the real config: 5 sources, correct
  tool list, `signed in: yes`. **Not applied** — that is the account owner's
  call.

## Not built, on purpose

- **A `Retry` that re-runs a sign-in automatically.** Every retry path here ends
  at a button a person presses. An automatic one is how a browser opens behind
  someone.
- **Merging any other connector family.** Only Google has five processes over
  one account; a general "merge connectors" facility would be machinery with one
  caller.
- **Blocking the turn while a connector finishes setting up.** The withheld
  tools plus a stated reason is the whole mechanism; waiting is what Phase 4's
  latency work removed.
