# ADR-0006: Skills Architecture

## Status

Proposed

## Context

Skills need to let the model follow packaged multi-step procedures without PSOK building a separate execution engine for them. Pipali's `SKILL.md`-directory model, discovered via progressive disclosure and executed through existing tools rather than a dedicated invoke mechanism, is the researched precedent. See [skills.md](../skills.md).

## Decision

Represent skills as filesystem directories under `~/.psok/skills/<name>/` containing a required `SKILL.md`, discovered by scanning and validating frontmatter, advertised in the system prompt by name, description, and path only (progressive disclosure), and invoked through the model reading the file with the existing `view_file` tool and executing its procedure with existing tools. No dedicated `invoke_skill` tool. No remote skill registry in v1.

## Alternatives Considered

- **A dedicated `invoke_skill` tool that executes a skill as a unit.** Rejected: this would make a skill a second execution primitive alongside tools, duplicating the dispatch, permission, and logging machinery tools already have, for no capability a skill needs that composing existing tools does not provide.
- **A remote skill marketplace/registry.** Rejected as premature infrastructure for a solo project; sharing a skill is sharing a directory.

## Trade-offs

Skill selection quality depends entirely on prompt-engineered descriptions with no programmatic router in v1; if the installed-skill count grows large, catalogue size becomes a context-budget cost with no compensating mechanism beyond writing better descriptions, until a `search_skills` deferred-loading tool (mirroring the MCP large-tool-set pattern) becomes justified.

## Consequences

Authoring a skill requires no code, no registration step, and no restart. A skill can never exceed what existing tools can already do, which keeps the tool surface as the single place capability actually lives.
