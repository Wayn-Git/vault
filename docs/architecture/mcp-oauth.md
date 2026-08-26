# MCP OAuth: How Connecting an App Actually Works

Companion to [mcp.md](mcp.md), which covers strategy. This one covers the flow that runs when a user clicks "connect" on GitHub, and the real-world complications found while building it.

## The flow

PSOK does not implement OAuth from scratch. The MCP Python SDK's `OAuthClientProvider` already implements discovery, dynamic registration, PKCE, and token refresh. PSOK supplies the three pieces the SDK deliberately leaves to the host application:

| Piece | PSOK's implementation |
|---|---|
| `storage` | `KeychainTokenStorage` — tokens in the OS keychain, never a file ([ADR-0012](decisions/0012-credential-storage.md)) |
| `redirect_handler` | Opens the system browser at the provider's own login page |
| `callback_handler` | A one-shot loopback HTTP server on `127.0.0.1:33418` |

End to end, when the user connects GitHub:

```
 1. PSOK connects anonymously to https://api.githubcopilot.com/mcp/
 2. Server replies 401 with
       WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource/mcp/"
 3. PSOK fetches that resource metadata          (RFC 9728)
       -> authorization_servers: [https://github.com/login/oauth]
       -> scopes_supported:      [repo, read:org, …]
 4. PSOK fetches the authorization server metadata (RFC 8414)
       -> authorization_endpoint, token_endpoint, PKCE S256 supported
 5. PSOK obtains a client_id — by dynamic registration where supported,
    otherwise from the one the user registered (see below)
 6. Browser opens at github.com/login/oauth/authorize with PKCE + state
 7. The user signs in and approves — on GitHub's real page, never inside PSOK
 8. GitHub redirects to http://127.0.0.1:33418/oauth/callback?code=…
 9. PSOK exchanges the code (plus the PKCE verifier) for tokens
10. Tokens go to the OS keychain; the connection retries and succeeds
```

A verified authorization URL from step 6:

```
https://github.com/login/oauth/authorize
  response_type         = code
  client_id             = <your registered app>
  redirect_uri          = http://127.0.0.1:33418/oauth/callback
  code_challenge_method = S256
  code_challenge        = OexPOyMUvBhbr1qo-_09hrWIo5GNJsdvagcgs0uUmzQ
  scope                 = repo read:org read:user user:email …
  state                 = vTkjcScUHVKXjON7wvMHJDdhb1KepU-qJF6FBz1k8FA
  resource              = https://api.githubcopilot.com/mcp/
```

The `resource` parameter is RFC 8707 audience binding: it stops a token minted for this MCP server being replayed against a different one.

## The complication: not every provider supports dynamic registration

The MCP spec expects dynamic client registration (RFC 7591) so a client can register itself on first contact. **GitHub does not implement it.** Its authorization server metadata advertises PKCE but publishes no `registration_endpoint`, and posting to the conventional path returns `404 page not found`.

That is not an error PSOK can retry past. So the OAuth layer supports two ways of obtaining a client:

- **Dynamic registration**, when the provider offers it — fully automatic, nothing for the user to do.
- **A pre-registered client**, seeded into token storage before the flow starts, which makes the SDK skip registration entirely.

When registration 404s, PSOK classifies the failure specifically rather than surfacing a bare exception:

```
$ psok mcp add github
added 'github' (streamable-http)

GitHub does not support automatic app registration, so register one once:
  1. https://github.com/settings/developers -> New OAuth App
  2. Authorization callback URL: http://127.0.0.1:33418/oauth/callback
  3. Generate a client secret
  4. psok mcp auth github --client-id <id> --client-secret <secret>
  5. psok mcp login github
```

This is the difference between a dead end and a five-step fix. The generic path produced `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)`, which tells the user nothing — so the connection layer now unwraps nested exception groups to the leaf cause before classifying it.

## Where secrets live

Nothing secret is ever written to `mcp.yaml`:

| Value | Where |
|---|---|
| Access and refresh tokens | OS keychain, `psok-mcp/<server>.tokens` |
| Registered client info | OS keychain, `psok-mcp/<server>.client` |
| OAuth client secret | OS keychain, `psok-mcp/<server>.client_secret` |
| OAuth **client id** | `mcp.yaml` — a public identifier, not a credential |
| Keychain references | `mcp.yaml` |

`psok mcp remove <name>` deletes the stored credentials along with the config entry, so removing a server does not leave tokens behind.

## Three catalogue shapes

The catalogue marks each entry with what a one-click add actually requires, because pretending they are all the same would mislead:

- **`none`** — works immediately. Playwright, Chrome DevTools, Fetch, Memory. Local stdio processes, no credentials.
- **`oauth`** — clicking through reaches the provider's real login page. GitHub.
- **`setup`** — needs credentials the user must obtain first. Google Workspace requires your own Google Cloud OAuth client, because Google does not permit a shared one for this use; the catalogue entry carries the exact steps.

## Sign-in does not block, and does not give up on the user

Three defects lived in this flow, all found by clicking Connect rather than by
reading it. They are worth recording because each one produced a *plausible*
failure message that pointed at the wrong thing.

**The connect deadline was shorter than the person it waited on.**
`MCPConnection.connect` armed `timeout_seconds` (60s) around
`session.initialize()`, and for an OAuth server that call contains the entire
browser sign-in — which the loopback callback allows 300s. At 60s PSOK
disconnected the transport mid-flow and recorded a circuit-breaker failure,
while the callback thread went on to serve the redirect and render *Connected*
in the browser. Both were telling the truth about different things.
`ServerConfig` now carries `auth_timeout_seconds` as well, and `_await_ready`
switches to it once `redirect_handler` has signalled that a human is what is
being waited on. A slow human is not a server fault, so that path does not trip
the breaker.

**A server that runs its own OAuth was killed mid-flow.** `_server_side_login`
spawned `workspace-mcp`, asked it for an authorization URL, opened the browser
— and then shut the manager down in `finally`. `workspace-mcp` binds its
`localhost:8765/oauth2callback` listener lazily *inside its own process*, so
Google's redirect arrived at a port nothing held. Microsoft To Do broke the same
way: a device-code flow needs the server alive to poll for completion, and PSOK
killed it the moment the code was displayed. Ownership of that manager now
passes to a watcher task which polls the credential store and tears the session
down when the sign-in lands, a deadline passes, or the user signs out.

**Signing in connected nothing.** `login` used a throwaway manager and shut it
down, so the live registry — which is what the interface reads and what turns
run against — never heard about it. The connector stayed under "Added, not
running" with a valid token sitting in the keychain. Sign-in now switches the
capability on and connects against the live manager, because "sign in" and "and
now use it" were never two things a user wanted separately.

**The request no longer waits for any of it.** `POST …/login` returns `202` in
milliseconds and the flow runs as a task; `GET /api/mcp/authorizations` carries
`status` (`waiting` → `done` | `failed`) with the reason, and the Connectors tab
already polled it. Holding the request open for up to five minutes was itself a
bug: nothing in a browser or a dev proxy waits that long, so a sign-in that was
going fine surfaced as a bare network error.

## "Invalid or expired OAuth state parameter"

That message comes from the *provider*, which made it look like a Google
problem. It was not. The `state` is a one-time CSRF nonce: the server that
issued it checks it when the browser comes back, and refuses if it has gone or
aged out. Five things in PSOK could destroy or outlive a state that had been
minted perfectly well, and the provider's refusal was the honest consequence of
each.

**Sign-out deleted the shared state store.** This was the direct cause.
`workspace-mcp` keeps in-flight states in `oauth_states.json`, in the same
credentials directory it keeps accounts in — and all nine Google connectors
share that one directory. `sign_out` did `shutil.rmtree` on it, so signing out
of Gmail destroyed the state a Calendar sign-in was about to have checked. The
user finished a good login and was told their state was invalid. `login(force=
True)` signs out first, so "switch account" did it to itself. `_clear_credentials_dir`
now empties the store while leaving `IN_FLIGHT_FILES` alone.

**A published link outlived the state behind it.** `PENDING` held a `waiting`
entry with a clickable URL indefinitely, while the state inside it expired in
five to ten minutes. The Connectors page offered those links forever, and
clicking one produced exactly this error. `PendingAuthorization` now carries
`started_at` and `ttl_seconds`, `live` says whether the link is still worth
offering, and the API sends `authorization_url: null` once it is not.

**A dead attempt blocked the retry.** The loopback wait held the fixed callback
port for its whole timeout even after the user had given up, so every retry hit
`CallbackPortUnavailable` for five minutes. The wait now stops and joins its
thread on cancellation, and a sign-in whose link has expired is superseded by a
new one rather than refused as "already in progress".

**A stray request consumed the callback.** `handle_request()` serves exactly one
request, whatever it is — a browser asking for `/favicon.ico` was enough. The
redirect then found nothing listening. The server now answers non-callback paths
404 and keeps waiting.

**Two flows shared one result slot.** `_CallbackHandler.result` was a class
attribute, so concurrent sign-ins could read each other's redirect, and each
flow's reset could erase the other's. The result lives on the server instance
now.

None of this weakens the check. The SDK still compares state with
`secrets.compare_digest` and rejects a mismatch; these were all about the state
surviving long enough to be compared.

## Sign-in does not block, and does not give up on the user

Three more defects lived in this flow, all found by clicking Connect rather than
by reading it.

**The connect deadline was shorter than the person it waited on.**
`MCPConnection.connect` armed `timeout_seconds` (60s) around
`session.initialize()`, and for an OAuth server that call contains the entire
browser sign-in, which the loopback callback allows 300s. At 60s PSOK
disconnected the transport mid-flow and recorded a circuit-breaker failure,
while the callback thread went on to serve the redirect and render *Connected*
in the browser. Both were telling the truth about different things.
`ServerConfig` now carries `auth_timeout_seconds` as well, and `_await_ready`
switches to it once `redirect_handler` has signalled that a human is what is
being waited on. A slow human is not a server fault, so that path does not trip
the breaker.

**A server that runs its own OAuth was killed mid-flow.** `_server_side_login`
spawned `workspace-mcp`, asked it for an authorization URL, opened the browser
— and then shut the manager down in `finally`. `workspace-mcp` binds its
`localhost:8765/oauth2callback` listener lazily *inside its own process*, so
Google's redirect arrived at a port nothing held. Microsoft To Do broke the same
way: a device-code flow needs the server alive to poll for completion, and PSOK
killed it the moment the code was displayed. Ownership of that manager now
passes to a watcher task which polls the credential store and tears the session
down when the sign-in lands, a deadline passes, or the user signs out.

**Signing in connected nothing.** `login` used a throwaway manager and shut it
down, so the live registry — which is what the interface reads and what turns
run against — never heard about it. The connector stayed under "Added, not
running" with a valid token sitting in the keychain. Sign-in now switches the
capability on and connects into the live manager, because "sign in" and "and now
use it" were never two things a user wanted separately.

**The request no longer waits for any of it.** `POST …/login` returns `202` in
milliseconds and the flow runs as a task; `GET /api/mcp/authorizations` carries
`status` with the reason, and the Connectors tab already polled it. Holding the
request open for up to five minutes was itself a bug: nothing in a browser or a
dev proxy waits that long, so a sign-in that was going fine surfaced as a bare
network error. The task must not build the registry before starting either —
that starts every switched-on connector serially, and the user is waiting for a
browser tab, not for Chrome DevTools to boot.

## "(invalid_client) The provided client secret is invalid"

The next error along, once the state survives: the flow reaches Google's token
endpoint and the *credential* is refused. Nothing about the flow is wrong here —
the secret is — but two things in PSOK made it far harder to see than it needed
to be, and one of them could cause it.

**One Google client was stored nine times.** The catalogue's setup hint promises
"you only do this once — every Google app then shares it", and
`shares_account_with="google"` says the same. The storage did the opposite: the
secret went to `psok-mcp/<connector>.env.GOOGLE_OAUTH_CLIENT_SECRET`, one entry
per connector. Regenerating a secret and pasting it on the Calendar panel left
the other eight on the old value, so Calendar worked and Gmail failed at token
exchange with a credential the user believed they had already replaced.
`set_env` now writes the reference onto every connector sharing the account, and
`env_secret_ref` names the entry for the account rather than for whichever
connector happened to be edited first.

**A malformed secret was only discovered by the provider.** Google issues
`GOCSPX-` plus 28 characters; a secret selected by hand rather than copied is
easy to clip, and one character short fails exactly like a wrong one — at the
very end of the flow, after the user has chosen their account, in a browser tab
PSOK cannot see. `reject_implausible_credential` refuses what is certainly wrong
at the moment it is entered, and the endpoint answers `400` with the reason
rather than storing it. It is deliberately narrow: an empty value, stray
whitespace, a missing prefix, a wrong length. A provider changing its format
must not lock anyone out of their own connector.

**And the credentials are checked before anything opens.** `check_google_client`
asks Google's token endpoint with a deliberately invalid code. Google validates
the client *before* the code, so `invalid_client` means the credentials are
wrong and `invalid_grant` means they are right — which is the answer this wants.
A wrong secret is now a sentence on the connector's page in about a second,
naming the page to fix it on, instead of a consent screen followed by a dead
end. Unreachable, slow, or unexpected answers return nothing: a network problem
is not a bad credential and must never block a sign-in that would have worked.

## Device-code sign-in

Microsoft To Do does not use a redirect at all: it hands back a short code and a
page to type it at. PSOK returned that text as the login function's return
value, and once the login endpoint stopped blocking, nothing read the return
value any more -- so the code was extracted nowhere and shown nowhere, and the
provider's page asked for something the user had never been given.

`PendingAuthorization` now carries `user_code` and the server's own
`instructions` verbatim. `_device_code_in` anchors on the word "code" rather
than hunting for anything code-shaped, because a bare pattern matches parts of
URLs, tenant ids and hex fragments -- and showing the wrong string to type is
worse than showing none and falling back to the server's wording. The card
renders it monospaced and spaced out, because a code is read character by
character and `1`/`l` is exactly where that goes wrong.

## A working credential is not editable from the menu

One OAuth client backs every connector in an account group. Overwriting it is
therefore not a per-connector edit: it takes all nine Google connectors down at
once, and the only symptom is the provider refusing to exchange a token at the
*end* of a sign-in -- a long way from the text field that caused it. That is
exactly how a clipped secret got in.

So once a secret is stored, the panel shows it and says what it is shared with,
and offers no input. The backend refuses too -- `POST …/env` and
`POST …/oauth-client` answer 409, and neither accepts a force flag -- because
hiding a control that still works is not a guarantee. Replacing one is
deliberate and lives in the terminal:

    psok mcp env <server> GOOGLE_OAUTH_CLIENT_SECRET <value> --secret --force

Only secrets. A client id is a public identifier and correcting one is
harmless, so refusing it would be friction with nothing behind it.

## Abandoning a sign-in

Closing the browser tab is how most abandoned sign-ins end, and nothing told
PSOK. `DELETE /api/mcp/servers/{name}/login` cancels one: it stops the task,
releases the callback port, and shuts down any subprocess held open behind it.
Waiting cards also carry the time they have left, so "is this going to sit here
forever" has a visible answer -- it is five minutes, and there is a button.

A `waiting` card is also corrected on read: if the connector turns out to be
signed in already, the entry is settled as `done`. A card telling someone to
finish a sign-in they have already finished is wrong, and they cannot dismiss
it.

## What the interface shows

One card per sign-in, in the state it is actually in — `connecting`, `waiting`,
`done`, `failed`, `cancelled`, `expired` — replacing a single amber strip that
could only say "waiting" and could only offer a link. `cancelled` is deliberately
its own state and not a failure: there is nothing to debug, the user said no.
`expired` explains that the link timed out and offers a new one, which is the
screen that would have prevented this bug being reported as a mystery.

A sign-in that needs no browser at all — a stored token being reconnected —
publishes `connecting` the moment the task starts, so the gap between "accepted"
and the outcome is never blank.

## Security properties

- **SSRF protection** runs at transport construction, so a URL resolving to a private or loopback address never opens a connection. Local servers are legitimate, so `allow_local: true` opts in per server.
- **MCP tools are never registered at low risk.** PSOK cannot inspect what an external server does, so its tools do not get the confirmation-free tier that vetted builtins get.
- **First call to a new server always confirms**, once per server. This is a trust-establishment event separate from per-call risk, and it is the guardrail that compensates for MCP servers running outside PSOK's sandbox — a gap Pipali has and does not cover.
- **Circuit breaker** per server, so one flapping server cannot degrade the rest.
- **A failed server is backed off, not written off.** `reconcile` used to skip
  anything with a recorded error permanently, so one refused DNS lookup left a
  connector dark for the rest of the session. It now holds off 60s, then 5min,
  then 30min — keeping the property that comment protected (no connect timeout
  at the head of every turn) without making a bad minute forever.
- **Tool names are namespaced** `{tool}__mcp__{server}`, so two servers offering `search` do not collide.

## Testing

Unit tests mock the transport, which proves nothing about whether MCP actually works — so there is a second suite (`pytest -m live`) that spawns real servers:

- the Memory server: discover 9 tools, create an entity, read the graph back
- Playwright: discover 24 browser tools including `browser_navigate` and `browser_click`
- GitHub: confirm it refuses anonymously and that the guidance is actionable
- a bad-argument call: confirm a server-side validation failure returns an error result rather than crashing the turn
