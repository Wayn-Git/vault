# Skills

A skill is not a new execution primitive. It is a packaged set of instructions the model reads through tools that already exist. See [components.md](components.md) for how this differs from a tool, an MCP tool, and an integration.

## Format

```
~/.psok/skills/<name>/
  SKILL.md           required
  scripts/           optional — run via run_shell_command
  references/        optional — read via view_file / grep_files
  assets/            optional
```

`SKILL.md` frontmatter:

```yaml
---
name: weekly-review
description: >
  Compile a weekly review from open tasks, recently modified notes,
  and calendar events, and draft a summary note.
version: 1.0.0
tags: [productivity, review]
requires_tools: [list_tasks, search_documents, write_file]
---
```

`name` must match the directory name and satisfy a slug pattern (lowercase, digits, hyphens, capped length). `description` must be non-empty and capped in length — it is the entire basis on which the model decides relevance, so it should say what the skill does and when to use it, not narrate its steps. `requires_tools` is advisory: it lets discovery warn if a skill references a tool that is not currently registered, but it is not enforced at load time.

The markdown body is the procedure itself — written as instructions to the model, not as documentation for a human maintainer. It may reference files under `scripts/` and `references/` by relative path.

## Storage and versioning

The directory name is the skill's identity. `version` is for the user's own tracking and for changelog purposes; discovery does not key off it, and there is no dependency resolution between skill versions.

**No remote skill registry or marketplace in v1.** A solo project does not need a distribution system for something that is a markdown file; sharing a skill is sharing a directory. This may be revisited if PSOK ever wants a community skill-sharing surface, but it is not infrastructure v1 needs.

Builtin skills ship inside the PSOK repository under `skills/builtin/` and are copied into `~/.psok/skills/` on first run, **without overwriting any skill the user has already edited** — the same seeding behaviour Pipali uses, checked by comparing against a stored hash of what was last seeded rather than by unconditional overwrite.

## Discovery

At startup, and on an explicit reload, PSOK scans `~/.psok/skills/*/SKILL.md`, parses and validates frontmatter, and caches `{name, description, path}` for every valid skill. Invalid skills are excluded from the catalogue and their validation errors are surfaced in a diagnostics view rather than silently dropped.

The cached catalogue — name, description, and filesystem path only, never the full body — is what gets injected into the system prompt. This is the same progressive-disclosure principle the AI runtime uses for tool discovery and the MCP layer uses for large tool sets from a single server: advertise cheaply, load the expensive content only when it is actually going to be used.

## Invocation

**There is no `invoke_skill` tool.** When the model judges a skill relevant from its name and description, it reads the full `SKILL.md` with the ordinary `view_file` tool — the same tool it would use to read any other file in the workspace. From there it follows the procedure using ordinary tools: `run_shell_command` for anything under `scripts/`, `view_file` or `grep_files` for anything under `references/`.

This has two consequences worth stating plainly. First, authoring a skill requires no registration step and no restart — dropping a new `SKILL.md` into the directory makes it usable on the next prompt assembly. Second, a skill cannot do anything a combination of existing tools could not already do; if a skill's procedure needs a capability that does not exist as a tool, the correct fix is to add the tool, not to work around its absence inside the skill.

## Selection

Selection is entirely the model's judgment, driven by the catalogue's name and description fields in the system prompt. There is no programmatic router, keyword matcher, or embedding-based skill retriever in v1. This means skill descriptions carry real weight — a vague description degrades selection accuracy with no compensating mechanism — and it is the reason the format asks for a description of *what the skill does and when to use it* rather than a title.

If the number of installed skills grows large enough that the catalogue itself becomes a meaningful fraction of the prompt budget, the next step is not a router but the same progressive-disclosure trick applied one level deeper — a `search_skills` tool, mirroring how large MCP tool sets get deferred loading. That is a scaling response, not a v1 requirement.

## Script dependencies

A skill's `scripts/` directory may carry its own dependency declaration — a `requirements.txt` fragment or a `pyproject.toml` snippet — and dependencies are installed automatically when the skill is added, so a skill can bring its own tooling (for instance, a document-generation skill needing a DOCX library) without PSOK's core dependency set growing to anticipate every skill anyone might write.

## Composition

Skills are expected to combine multiple tools, integrations, and MCP calls in one procedure — that composition is the entire reason skills exist rather than PSOK simply relying on the model's raw judgment every time. A well-written skill turns a multi-step, easy-to-get-wrong procedure ("check for calendar conflicts before creating a task, and if there's a conflict, propose alternatives") into a single reusable instruction set, without requiring a single line of new code.
