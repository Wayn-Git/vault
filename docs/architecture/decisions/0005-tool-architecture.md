# ADR-0005: Tool Architecture

## Status

Proposed

## Context

PSOK needs builtin capabilities (filesystem, shell, scheduling), integration-provided capabilities (Gmail, Calendar, GitHub), and MCP-provided capabilities (external servers) to all be usable by the model. LibreChat's `builtin | mcp | action | custom` taxonomy, unified behind one LangChain tool interface, is the researched precedent. See [components.md](../components.md).

## Decision

Unify builtin, integration, and MCP tools behind one flat Tool Registry sharing a single JSON-Schema contract and result envelope. Source differences (in-process function, integration module, external MCP process) live only in each tool's implementation module, never in the model-facing contract or in the agent loop's dispatch logic.

## Alternatives Considered

- **Separate registries or calling conventions per source (a builtin-tool list, a separate MCP-tool list).** Rejected: this is what LibreChat's now-coexisting legacy manifest-based loader and newer typed registry look like mid-migration, and the research flagged it as unresolved complexity worth avoiding by not creating it in the first place.
- **Exposing MCP tools to the model differently from builtin tools (e.g., through a distinct meta-tool).** Rejected: adds model-facing complexity for no security or clarity benefit, since the permission gate already accounts for source at dispatch time regardless of how the tool is presented.

## Trade-offs

Because the model cannot tell tool sources apart, all source-specific policy (MCP first-call confirmation, integration credential handling) must be enforced entirely at the dispatcher, with no help from prompt-level signaling. This is treated as a feature, not a cost — it is exactly what keeps the model's tool-selection reasoning simple.

## Consequences

One dispatch path, one registry, one place to add cross-cutting behavior (logging, redaction, risk evaluation) that automatically applies to every tool regardless of source.
