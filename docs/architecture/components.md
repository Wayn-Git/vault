# Components: Tool, Skill, MCP Tool, Agent

These four words are used loosely across the ecosystem PSOK borrows from. This document fixes their meaning inside PSOK. Getting these boundaries wrong is how systems end up with three overlapping plugin mechanisms, so the definitions here are deliberately narrow and the rule for choosing between them is deliberately mechanical.

## Tool

**A tool is a single atomic capability with a fixed JSON-Schema contract, executed in-process by PSOK's own code.**

Examples: `read_file`, `write_file`, `grep_files`, `run_shell_command`, `open_url`, `create_task`, `find_free_slot`, `search_documents`.

Properties:

- It has a name, a description, and a JSON Schema for its arguments. That triple is the entire contract the model sees.
- It is stateless with respect to the loop. Any state it needs comes from its arguments or from the data layer.
- It returns the standard result envelope — text content, optional artifacts, an error flag — never an exception.
- It declares a static risk level used by the permission gate.

The tool is the *only* unit the model can invoke. Everything else in this document is either something that becomes a tool, or something that is not model-facing at all.

## Skill

**A skill is a packaged directory of instructions that teaches the model a multi-step procedure composed of existing tools. It is not an execution mechanism.**

A skill lives at `~/.psok/skills/<name>/` and contains a required `SKILL.md` with YAML frontmatter, plus optional `scripts/`, `references/`, and `assets/` directories.

The critical property: **there is no `invoke_skill` tool.** Skills are advertised in the system prompt by name, description, and path only. When the model judges a skill relevant, it reads the full `SKILL.md` with the ordinary `view_file` tool, then follows the procedure using ordinary tools — running `scripts/*` through `run_shell_command`, reading `references/*` through `view_file` or `grep_files`.

This makes a skill closer to a runbook than to a plugin. Adding one is dropping a markdown file into a directory. There is nothing to register, compile, or restart.

A skill can and generally should combine multiple tools and MCP calls — composing capability is its entire purpose. What it cannot do is provide capability that does not already exist as a tool. A skill that needs a new primitive requires a new tool first.

See [skills.md](skills.md) for format, discovery, and versioning.

## MCP Tool

**An MCP tool is a tool whose implementation lives in an external process PSOK does not own, reached over the Model Context Protocol.**

It enters the same flat registry as every builtin tool, under a composite key (`{tool}__mcp__{server}`) that prevents collisions between servers offering same-named tools. Its results are normalized into the standard envelope before the agent loop sees them.

**From the model's point of view an MCP tool is indistinguishable from a builtin tool.** The difference is entirely in how the call is implemented — an in-process function versus a JSON-RPC round trip to a subprocess or remote endpoint — plus two operational facts the dispatcher knows and the model does not: MCP servers run outside PSOK's sandbox, and each new server requires a one-time trust confirmation.

See [mcp.md](mcp.md).


## Agent

**An agent is a named configuration of the loop: a persona, a curated subset of tools and skills, and a default model.**

**PSOK v1 ships exactly one agent** — the Director, running with the full catalogue. Named agents and sub-agent delegation are deliberately deferred.

The reasoning: multiple agents solve a problem PSOK does not have yet. A single user with a single machine has one context. Sub-agent delegation adds a scheduling problem, a context-passing problem, and a debugging problem, all in exchange for benefits that appear only when tasks are large enough to parallelize. The architecture does not preclude it — the loop takes its catalogue and persona as inputs, so a second configuration is additive — but building it now would be building for an imagined future.

Where "agent" appears elsewhere in these documents without qualification, it means the Director.

## The distinctions in one table

| | Model-facing? | Implemented by | Owns credentials? | Owns state? | Added by |
|---|---|---|---|---|---|
| **Tool** | Yes, directly | PSOK, in-process | No | No | Writing code + registering |
| **Skill** | Indirectly (advertised, then read) | Nothing — composes tools | No | No | Dropping a directory in |
| **MCP tool** | Yes, as a tool | External process | Per-server, if any | External | Editing `mcp.yaml` |
| **Agent** | No — it *is* the caller | PSOK | No | Conversation | (v1: one, fixed) |

## The decision rule

When a new capability is needed, work down this list and stop at the first match. The ordering is by cost and risk: earlier options are cheaper to build, easier to secure, and easier to debug.

**1. Can PSOK's own backend do this directly against a local resource — filesystem, shell, local database, scheduling?**
→ **Build a tool.** This is the default and should stay the most common answer.

**2. Is this a multi-step procedure that only recombines tools that already exist, mostly consisting of instructions, templates, and judgement?**
→ **Write a skill.** No code, no deployment, no registration. If you find yourself writing a tool whose implementation is "call these three tools in order," it was a skill.

**3. Does a good MCP server already exist for this — a browser, an external account, an ad-hoc web API?**
→ **Configure an MCP server.** This is how PSOK reaches anything outside the local machine.

**4. Does this need a fundamentally different reasoning strategy or persona running semi-independently?**
→ **A future agent.** Not in v1. Record it and move on.

### Worked examples

| Need | Answer | Why |
|---|---|---|
| Read a file from the vault | Tool | Local resource, PSOK's own code |
| "Prepare my weekly review": gather tasks, scan notes, draft a summary | Skill | Pure composition of `list_tasks`, `search_documents`, and the model's own writing |
| Search my email | MCP server | An external account, reached through a server that owns its own auth |
| Create a GitHub issue | MCP server | GitHub publishes one; PSOK signs in over OAuth |
| Click through a web page and fill a form | MCP server | Existing browser-automation server, stateless from PSOK's side |
| Resolve "next Tuesday" into a date | Neither — internal engine | Not model-facing at all; the scheduling engine does this inside `create_task` |
| Fetch the current weather | MCP server, or a small tool | Judgement call; if an MCP server exists, use it — nothing needs persisting |
| Send an email | MCP tool, confirmed before it runs | Outward-facing and irreversible; see [security.md](security.md) |

### The trap this rule is built to avoid

The failure mode is capability arriving through whichever mechanism the person adding it happened to like. Then the same conceptual action exists as a tool, a skill, and an MCP server, with three permission stories and three failure modes.

The rule prevents that by making the choice a function of the capability's properties — locality, statefulness, credential ownership — rather than of convenience. When two options genuinely tie, prefer the earlier one on the list.
