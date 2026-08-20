# MCP Strategy

LibreChat's MCP layer is production-hardened well beyond spec compliance, but a large fraction of its complexity exists specifically because it serves many users who are not the operator: per-user connection pools, on-behalf-of token exchange, cluster leader election, admin-versus-user trust tiers. PSOK has one user who is also the operator of every MCP server it configures. This document keeps the parts of LibreChat's design that hold value regardless of tenancy, and drops the parts that only make sense at LibreChat's scale.

## What PSOK keeps

**Three transports: stdio, SSE, streamable-HTTP.** LibreChat supports four, adding WebSocket for breadth. No commonly used MCP server currently requires WebSocket specifically; PSOK adds it if and when a real server does, rather than carrying an unused transport implementation and its test surface from day one.

**SSRF protection on URL-based transports.** Private-IP and CIDR-range blocking, applied at transport construction so a malicious or misconfigured server URL never establishes a connection. This matters precisely because PSOK is trusted-by-default (see below) — the guardrail here is not "is this server trustworthy" but "does this URL actually point somewhere the user intended," which protects against a bad URL reaching internal network services regardless of trust level.

**Composite tool-key namespacing.** Every discovered tool is registered as `{tool_name}__mcp__{server_name}`, so two servers offering same-named tools never collide in PSOK's one flat tool namespace. This is a one-line policy decision with a real payoff once more than one server is configured.

**Uniform result normalization.** MCP content blocks — text, resources, images — are converted into the same `{text, artifacts, error}` envelope every other tool result uses, before the result reaches the agent loop or any provider-specific code. The agent loop never learns that a result came from an external process.

**Per-server circuit breaking.** A server that fails repeatedly within a time window stops being retried for a backoff period, so one flapping MCP server cannot degrade the whole system's responsiveness.

**Bounded tool discovery.** `tools/list` calls are capped on page count, tool count, response size, and elapsed time, protecting startup from a broken or hostile server advertising an unbounded tool set.

## What PSOK collapses

LibreChat's `MCPServerSource` distinguishes four origins — `yaml` (operator-configured, boot-time, full trust), `config` (admin database override, full trust), `user` (submitted through a UI, restricted schema), `plugin` (bundled) — because in a multi-tenant deployment the administrator and the end user are different people with different trust levels, and the system must defend the operator's servers against something an end user might submit.

**In PSOK those are the same person.** There is no untrusted submitter to defend against, so PSOK collapses to two categories, both full trust:

- **`configured`** — anything in the user's own `mcp.yaml`. stdio is allowed. `${VAR}` environment interpolation is allowed. This is the entirety of what most users will ever touch.
- **`bundled`** — first-party-recommended servers PSOK ships templates for (for instance a browser-automation server), offered during onboarding rather than silently auto-installed.

There is no third, restricted tier, because restricting configuration the user wrote for themselves protects against nothing. What the two-tier collapse does **not** remove is the underlying fact LibreChat's restricted schema encodes correctly: **stdio grants arbitrary command execution.** That fact is documented in PSOK's threat model and enforced through the [security](security.md) layer's first-call-to-new-server confirmation, rather than through a config-schema restriction that would have no one to restrict.

## What PSOK drops entirely

- **On-behalf-of token exchange.** Exists to convert one user's identity into a downstream-scoped token for a different user's request in a shared deployment. PSOK's every credential belongs to the same person; there is no downstream identity to scope to.
- **Per-user connection pools with refcounting.** One user needs one pool.
- **Cluster leader election and Redis-backed shared caches.** These solve "many replicas need to agree," a problem that does not exist in a single process on a single machine.
- **Admin-versus-user server management APIs.** There is one settings surface, not an admin console and a user console.

If a configured MCP server itself requires OAuth, PSOK supports plain single-user OAuth2 authorization-code login, once per server, with the resulting token stored in the same keychain-backed credential store Integrations use — not the on-behalf-of machinery.

## Configuration

```yaml
# ~/.psok/config/mcp.yaml
mcpServers:
  chrome-devtools:
    transport: stdio
    command: npx
    args: ["-y", "chrome-devtools-mcp"]
    source: bundled

  my-notes-server:
    transport: streamable-http
    url: https://notes.example.internal/mcp
    headers:
      Authorization: "Bearer ${MY_NOTES_TOKEN}"
    source: configured
```

`${VAR}` interpolation resolves from environment variables or, for anything secret-shaped, a keychain reference resolved at connection time — never a literal secret in this file.

**Credentials a server takes through its environment** follow the same rule as every other secret: an `env` value written as `keychain:<ref>` is resolved from the OS keychain when the server is spawned, so `mcp.yaml` holds the reference and never the value ([ADR-0012](decisions/0012-credential-storage.md)). `psok mcp env <server> KEY=VALUE --secret` writes both halves.

## Discovery, namespacing, and execution

1. On startup (for servers marked to start eagerly) or on first use (lazily, for the rest), PSOK connects using the transport-appropriate client, applying SSRF checks for URL transports.
2. `tools/list` is called with the discovery budgets described above; results are cached in memory and invalidated on a tool-list-changed notification from the server.
3. Each discovered tool is registered into the flat tool registry under its composite key and its JSON Schema is validated and normalized the same way any tool schema is.
4. A call to an MCP tool goes through the identical dispatch path as any other tool call: risk-floor lookup (MCP tools default to at least medium risk, since PSOK cannot inspect what an external server actually does), first-call-to-server confirmation if this server has not been used before, execution over the transport with the connection's timeout, result normalization, and audit logging.
5. Errors — connection failure, timeout, malformed response, the server itself returning an error — are caught and rewritten into a descriptive string that becomes the tool's result content with the error flag set, so the model sees specifically what went wrong rather than the run terminating.

## When to reach for MCP versus a builtin tool or an Integration

This restates the relevant branch of the decision rule in [components.md](components.md): reach for MCP when a good server already exists for an on-demand capability that PSOK does not need to persist data from locally — browser automation, an ad-hoc web API, a niche one-off service. Build a builtin tool or an Integration instead when the data needs to live in PSOK's own database to be cross-referenced with tasks, calendar, or memory, or when PSOK wants to own the credential lifecycle directly rather than delegate it to a server's own auth handling.
