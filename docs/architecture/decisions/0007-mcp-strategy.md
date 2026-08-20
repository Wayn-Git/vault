# ADR-0007: MCP Strategy

## Status

Proposed

## Context

LibreChat's MCP layer (researched in [librechat.md](../../research/librechat.md)) is production-hardened for a multi-tenant deployment: four transports, four trust tiers, OAuth on-behalf-of token exchange, per-user connection pools, and cluster-coordinated boot-time discovery. PSOK is single-user and single-process. See [mcp.md](../mcp.md).

## Decision

Adopt a reduced MCP layer: three transports (stdio, SSE, streamable-HTTP — no WebSocket in v1), a single full-trust model collapsed to two categories (`configured` and `bundled`, since administrator and end user are the same person), SSRF protection on URL transports, composite tool-key namespacing, uniform result normalization, and per-server circuit breaking. Explicitly exclude OAuth on-behalf-of token exchange, per-user connection pooling, cluster leader election, and Redis-backed distributed caches.

## Alternatives Considered

- **Adopt LibreChat's MCP layer as-is.** Rejected: the excluded machinery exists to solve multi-tenancy problems PSOK does not have, and would be maintained indefinitely for no benefit.
- **A minimal MCP client with no SSRF protection, namespacing, or circuit breaking.** Rejected: these protect against real failure modes (a bad URL, a colliding tool name, a flapping server) regardless of tenancy, and are cheap to keep.

## Trade-offs

The two-tier trust collapse removes LibreChat's schema-level restriction on user-submitted servers (no stdio, no variable interpolation). Because there is no separate untrusted submitter in PSOK, this restriction protects nothing; the underlying fact it encodes — stdio grants arbitrary command execution — is instead handled by [security.md](../security.md)'s first-call-to-new-server confirmation requirement.

## Consequences

MCP support without a distributed-systems layer. Adding an MCP server is a YAML edit. If a server needs OAuth, PSOK supports single-user authorization-code login into the same keychain-backed credential store integrations use, not the on-behalf-of exchange.
