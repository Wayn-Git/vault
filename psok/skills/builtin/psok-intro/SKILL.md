---
name: psok-intro
description: >
  Explain what PSOK can currently do and check the health of its components.
  Use when the user asks what PSOK is, what it can do, what tools or skills are
  available, or why something is not working.
version: 1.0.0
tags: [meta, help]
---

# Introducing PSOK

Use this skill when the user wants to know what the system can do, or when
something appears misconfigured and you need to diagnose it.

## Establishing the current state

Run `psok doctor` with `run_shell_command` (read-only, so it will not prompt).
It reports the PSOK home directory, whether the database exists, which model
providers are configured, how many tools are registered, how many skills loaded
and which failed validation, and whether an OS sandbox is available.

Read the output before answering. Do not describe capabilities the doctor output
contradicts — if no providers are configured, say so rather than listing what
PSOK could do once one is.

## Explaining the system

PSOK reaches the user's world through four kinds of thing, and the distinction
matters when explaining what is possible:

- **Tools** are single actions PSOK performs directly: reading and writing
  files, searching them, running shell commands, opening applications, creating
  tasks and calendar events.
- **Skills** — like this one — are procedures written in markdown that combine
  existing tools. They add no new capability; they encode how to use what is
  already there.
- **MCP servers** are external processes providing tools PSOK did not write.
- **Integrations** connect an external account such as Gmail or Calendar, and
  own its credentials and sync.

## Explaining the permission model

If the user asks why they are being prompted:

Every tool has a fixed risk level. Low-risk reads run without asking. Writes and
anything outward-facing ask first. Anything touching credential directories asks
regardless of prior approval, and cannot be silenced. Choosing "always" for an
operation records that preference; `psok logs` shows every tool call with the
decision that allowed it.

## Diagnosing a failure

1. `psok doctor` first, always.
2. If a tool failed, check `psok logs --limit 10` for the recorded error.
3. If the sandbox is unavailable, that is expected on Windows and on Linux
   without bubblewrap installed — shell commands then run in direct mode and
   always ask for confirmation. Say this plainly rather than treating it as a
   fault.
