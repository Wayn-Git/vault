# ADR-0015: Desktop/GUI Automation Scope

## Status

Proposed

## Context

The brief's examples include desktop/file-system interaction, but do not require generic GUI automation (mouse/keyboard synthesis, screenshot-driven clicking). Pipali itself has no such layer, delegating GUI-shaped actions to a bundled, unsandboxed browser-automation MCP server. See [security.md](../security.md#desktop-scope).

## Decision

v1 desktop tools are limited to `open_application`, `open_url`, and `open_file` — OS default-handler launches only. Full screen-reading and click-based automation ("computer use") is explicitly deferred to a later, separately risk-gated phase.

## Alternatives Considered

- **Build full computer-use-style GUI automation in v1.** Rejected: it is the single highest-risk, highest-complexity capability surface available to build, and none of the brief's concrete examples require it.
- **Delegate all desktop interaction to a bundled MCP server, as Pipali does with browser control.** Deferred rather than rejected outright — this remains a reasonable path for a later phase, but is not adopted by default in v1 given that MCP servers run outside PSOK's sandbox (see [security.md](../security.md)).

## Trade-offs

Users who want richer desktop automation than launching applications/URLs/files will not have it in v1. Documented explicitly as a scope decision rather than left as a silent gap, so it is revisited deliberately rather than discovered as a missing feature.

## Consequences

The v1 attack surface for desktop interaction is small and easy to reason about. Full GUI automation, when eventually built, gets its own dedicated risk analysis and permission design rather than inheriting the fs/shell risk model by default.
