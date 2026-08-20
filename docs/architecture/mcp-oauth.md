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

## Security properties

- **SSRF protection** runs at transport construction, so a URL resolving to a private or loopback address never opens a connection. Local servers are legitimate, so `allow_local: true` opts in per server.
- **MCP tools are never registered at low risk.** PSOK cannot inspect what an external server does, so its tools do not get the confirmation-free tier that vetted builtins get.
- **First call to a new server always confirms**, once per server. This is a trust-establishment event separate from per-call risk, and it is the guardrail that compensates for MCP servers running outside PSOK's sandbox — a gap Pipali has and does not cover.
- **Circuit breaker** per server, so one flapping server cannot degrade the rest.
- **Tool names are namespaced** `{tool}__mcp__{server}`, so two servers offering `search` do not collide.

## Testing

Unit tests mock the transport, which proves nothing about whether MCP actually works — so there is a second suite (`pytest -m live`) that spawns real servers:

- the Memory server: discover 9 tools, create an entity, read the graph back
- Playwright: discover 24 browser tools including `browser_navigate` and `browser_click`
- GitHub: confirm it refuses anonymously and that the guidance is actionable
- a bad-argument call: confirm a server-side validation failure returns an error result rather than crashing the turn
