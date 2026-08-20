# Security: Permissions, Sandboxing, Credentials, Audit

PSOK gives an AI agent access to a real machine's filesystem, shell, and outbound network — including irreversible actions like sending email and creating calendar events. This document is the single place describing what stops the agent from doing something the user did not want.

## The permission gate

### Static risk floor, model self-report as refinement only

Pipali's confirmation gate is driven primarily by the model's own self-reported risk classification (`operation_type: safe/unsafe`, or `read-only/write-only/read-write`). That is a real weakness: the model can misjudge or misreport its own action, and the entire safety property then rests on that judgment.

PSOK inverts the priority. **Every tool declares a static risk level at registration time** — a property of the tool, not of any particular call:

| Risk | Examples | Default gate |
|---|---|---|
| Low | `read_file`, `list_files`, `search_documents`, `gmail_search`, `find_free_slot` | No confirmation |
| Medium | `write_file`, `edit_file`, `create_task`, `calendar_create_event` | Confirm unless previously "don't ask again" for this operation |
| High | `delete_file`, `run_shell_command` (direct mode), `gmail_send`, any first call to a new MCP server | Always confirm |

**The model's self-reported classification can only escalate this floor, never lower it.** It remains genuinely necessary in two places where static analysis cannot reach: an arbitrary shell command string, and an opaque MCP tool call whose semantics PSOK cannot inspect. There, the model's self-report adds information the static table cannot have — but it adds risk upward only. A tool statically rated medium that the model calls "safe" still confirms at medium; a tool statically rated low that the model flags as touching something sensitive escalates to confirm.

This closes Pipali's own documented gap while keeping the part of its design that earns its keep.

### The confirmation service

One component, reachable from every tool through the dispatcher, transport-agnostic exactly as in Pipali: it takes a callback, knows nothing about WebSockets or HTTP, and can therefore serve a CLI, a web UI, or a scheduled unattended run identically.

- **"Don't ask again"** persists a skip preference keyed by `operation[:subtype]` — for instance `run_shell_command:read-only` — in `confirmation_preferences`, so approving read-only shell use does not silently approve destructive use.
- **Timeout is long** (hours, not seconds), because a scheduled background task waiting on confirmation should still be answerable when the user next opens PSOK, not abandoned.
- **Every decision is logged** to `execution_logs` — auto-approved by risk floor, approved by the user, denied, or skipped by a standing preference — so the audit trail shows not just what ran but why it was allowed to.

### Sensitive-path denylist

Independent of sandbox and confirmation: reads or greps touching `.ssh`, `.aws`, `.gnupg`, `.env`, shell history files, browser profile directories, or PSOK's own config and keychain-reference paths force confirmation regardless of any other setting or standing preference. This cannot be silenced by "don't ask again."

## Sandboxing

Two shell execution modes, mirroring Pipali:

- **`sandbox`** (default) — OS-native containment; skips confirmation because the OS is trusted to enforce the boundary.
- **`direct`** — full access; always confirms.

Declarative policy in `sandbox.yaml`: denied read paths (credentials, secrets), allowed write paths (the workspace root, a scratch directory), allowed network domains (package registries, configured model provider APIs), and whether local port binding is permitted.

**macOS** uses Seatbelt (`sandbox-exec`); **Linux** uses Bubblewrap (`bwrap`), invoked as a subprocess wrapper around the command rather than through a bundled JS runtime package, since PSOK's backend is Python. **Windows has no sandbox in v1** — every shell command there is direct-mode and confirmation-gated, stated plainly rather than left implicit. Revisiting this (WSL2 as a sandbox substitute) is a roadmap note, not a v1 requirement. Recorded in [ADR-0009](decisions/0009-local-computer-shell-execution-permissions.md).

Background shell processes are capped at 3–5 concurrent (lower than Pipali's 10, matched to single-user scale), write logs rather than piping output, and terminate via SIGTERM with a grace period before SIGKILL.

### MCP servers sit outside the sandbox — and that gap gets a guardrail

MCP servers run as external processes (subprocess, or a remote endpoint over SSE/streamable-HTTP) that PSOK does not and cannot sandbox in the way it sandboxes its own shell commands. This is an accepted, documented risk, not an oversight — Pipali has the identical gap and does not compensate for it.

PSOK adds one guardrail Pipali lacks, cheap because PSOK controls MCP configuration end-to-end: **the first call to any newly configured MCP server always requires confirmation**, regardless of that call's self-reported risk. This establishes trust once per server rather than never. It composes with, rather than competes against, the ordinary risk-floor gate: first-call confirmation is a one-time trust-establishment event; every subsequent call from that server falls under the normal per-tool risk-floor-plus-escalation flow like any other tool. See [mcp.md](mcp.md).

## Desktop scope

v1 desktop interaction is deliberately narrow: `open_application`, `open_url`, `open_file` — OS default-handler launches, nothing more. No mouse or keyboard synthesis, no screenshot-driven clicking, no generic "computer use" loop.

This is a scope decision, not a gap: none of the task brief's concrete examples (organizing tasks, searching Gmail, moving files, running commands, delegating to a model) require full GUI automation, and it is the single highest-risk, highest-complexity surface available to build. It is deferred to a later, separately risk-gated phase — see [ADR-0015](decisions/0015-desktop-gui-automation-scope.md) and the roadmap's stretch phase.

## Credential isolation

Every secret — provider API keys, OAuth tokens for Gmail, Calendar, GitHub, and any MCP server that needs its own auth — lives in the OS keychain, reached through Python's `keyring` library. The database and every config file hold only a reference name, never a value.

Practical consequences of this rule:

- A tool that needs a credential resolves it from the keychain at call time, inside the tool implementation. The credential never appears in a prompt, a tool argument the model constructs, or a log line.
- `execution_logs` arguments and results pass through a redactor before being written, matching known credential-shaped fields and value patterns, so a tool that carelessly echoes a token back does not leak it into the audit trail.
- OAuth flows (Google, GitHub) write their resulting tokens directly to the keychain from the auth callback handler; the token is never round-tripped through the agent loop or a tool result.

Recorded in [ADR-0012](decisions/0012-credential-storage.md).

## Auditability

Every tool call, from every source — builtin, integration, MCP — writes one `execution_logs` row: tool name, source, redacted arguments, a result summary, risk level, the confirmation decision and by what path it was reached, duration, and outcome. Combined with the normalized `messages` history, the full trajectory of any conversation is reconstructable after the fact — what the agent tried, what the user approved or denied, and why.

## How the pieces compose

A single tool call at dispatch time passes through, in order:

1. **Static risk floor** lookup for the tool.
2. **Sensitive-path check**, if the call touches a path.
3. **Self-reported escalation**, if the tool provides one and it exceeds the floor.
4. **First-call-to-server check**, if the call is to a not-yet-trusted MCP server.
5. **Standing preference check** — does a "don't ask again" skip apply at the resulting level.
6. **Confirmation**, if none of the above resolved it automatically.
7. **Execution**, inside the sandbox if the tool is sandbox-capable and sandbox mode is active.
8. **Redaction and audit-log write**, regardless of outcome.

Nothing skips this path. There is no second way for a tool call to reach the operating system, the filesystem, or an external service.
