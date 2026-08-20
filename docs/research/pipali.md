# Pipali: Computer Interaction, Shell, Skills, Tool Execution

Repository: `/home/wayne/Documents/GitHub/pipali` — Bun + Hono backend, React 19 frontend, Tauri desktop wrapper.

`CONTRIBUTING.md` contains an architecture section with diagrams that is largely accurate against the code and is the best starting point for anyone re-verifying this research.

## 1. What was investigated

How an AI agent is given controlled access to the user's machine. Specifically: how desktop and filesystem actions are represented and executed, what actually runs shell commands and how that execution is contained, what a "skill" is as a concrete artifact, and the complete path a request travels from the user through the agent to the operating system and back.

Deliberately not investigated: the frontend, the Tauri packaging, authentication, billing, and any feature not bearing on local execution or agent capability structure.

## 2. Relevant architecture

### Local action surfaces

Pipali has **no generic operating-system automation layer**. There is no mouse control, no keyboard synthesis, no screenshot-and-click loop. The agent reaches the machine through exactly two first-party surfaces plus one delegated one:

- **Filesystem actors** — `view_file`/`read_file`, `list_files`, `grep_files`, `edit_file`, `write_file`, each a small module under `src/server/processor/actor/`. These are ordinary Node/Bun `fs` calls. There is no operating-system abstraction layer between the tool and the filesystem; platform differences are handled ad hoc through `path` and `os`.
- **Shell execution** — a single `shell_command` actor, covered in detail below. Everything that is not a file read or write goes through here: process control, package installation, running scripts.
- **Browser interaction, delegated to MCP** — GUI-shaped actions (`click`, `drag`, `fill_form`, `hover`, `press_key`, `take_screenshot`, `navigate_page`) come from a bundled MCP server wrapping `chrome-devtools-mcp`, auto-installed on first run in `src/server/init.ts`. This is Pipali's de facto desktop-interaction layer, but it is scoped to a Chrome instance rather than the whole desktop.

The important structural point is that "desktop control" was never built as its own subsystem. It is either a file operation, a shell command, or an external MCP server.

### Permission model

A single **confirmation service** (`src/server/processor/confirmation/confirmation.service.ts`) gates every dangerous operation: `edit_file`, `write_file`, `delete_file`, `execute_command`, `mcp_tool_call`, `read_sensitive_file`, `grep_sensitive_path`, `fetch_internal_url`.

Three design properties make this work well:

- **Transport-agnostic.** The service takes a `ConfirmationCallback`. The WebSocket layer (`src/server/routes/ws/confirmation-manager.ts`) supplies a callback that publishes a request to a per-conversation event bus and waits for the client to answer. The service itself knows nothing about WebSockets, HTTP, or the UI. Timeout is generous (24 hours) so unattended and scheduled runs can still be approved later.
- **Risk levels and persisted skip-keys.** Each operation derives a `low`/`medium`/`high` risk level. When the user chooses "yes, don't ask again," a skip-key such as `execute_command:read-only` is persisted per user in the database. The granularity is `operation[:subtype]`, which is fine enough that approving read-only commands does not silently approve destructive ones.
- **Sensitive-path detection independent of the sandbox.** `src/server/security/path-validator.ts` holds a regex list covering `.ssh`, `.aws`, `.gnupg`, `.npmrc`, `.env`, shell history, and browser profile directories. Reads and greps touching those paths force confirmation regardless of any other setting.

The weak point, discussed under trade-offs, is where the risk classification comes from.

### Shell execution and sandboxing

`src/server/processor/actor/shell_command.ts` is the only component that executes shell commands, exposed to the model as one tool whose schema is declared inline in the director (`src/server/processor/director/index.ts`), alongside a companion `stop_process` tool.

Two execution modes exist and they are **alternatives, not layers**:

- `sandbox` (the default) — the command is wrapped by OS-native sandboxing and **skips confirmation entirely**, trusting the operating system to enforce the boundary.
- `direct` — full access, no sandboxing, **requires user confirmation**.

There is no "sandboxed and confirmed" tier. The sandbox itself (`src/server/sandbox/`) is a thin wrapper over `@anthropic-ai/sandbox-runtime`, which uses Seatbelt (`sandbox-exec`) on macOS and Bubblewrap (`bwrap`) on Linux. Configuration is declarative — allowed and denied read/write paths, allowed network domains, local-binding permission — with defaults that deny reads of credential directories, allow writes to `/tmp` and the app's own directory, and allow network access to package registries and model APIs. Settings persist per user in the database and reload at runtime.

**Windows has no sandbox at all.** On Windows every shell command falls back to direct execution with confirmation. This is a materially different security posture per platform and any threat model has to state it explicitly rather than assume uniform containment.

## 3. Important implementation details

- **Platform dispatch** picks `/bin/bash -c` on macOS and Linux, PowerShell on Windows, and the tool description text shown to the model differs per platform so the model writes commands in the right dialect.
- **Output capture** uses piped stdout and stderr; a non-zero exit code is appended to the returned output rather than signalled out of band. Sandbox violations are detected either from the sandbox runtime's own annotation or by pattern-matching `EPERM` and "Permission denied", and a note is injected telling the model it may retry in `direct` mode. That note is what turns a hard failure into a recoverable one.
- **Timeouts** default to 30 seconds with a 60-second in-process ceiling, even though the advertised schema allows far more; the value is clamped internally. A timeout produces a normal tool result, not an exception.
- **Every failure mode returns a structured string** — bad working directory, empty command, timeout, spawn error. Nothing throws out to the agent loop. This is the single most important implementation habit in the file: the loop always receives something to reason about, so a failed tool call never terminates the run.
- **Background execution** (`run_in_background: true`) hands off to `src/server/events/background-processes.ts`. Output goes to a log file rather than a pipe; the agent receives a pid and a log path and polls with `tail` or `grep` through subsequent shell calls. Process exit is delivered asynchronously back into the conversation. Concurrency is capped at 10, and stopping a process escalates SIGTERM to SIGKILL after a two-second grace period.
- **Output truncation** happens centrally in the director at a 100k-character cap, not per tool.
- **Uniform result shape.** Nearly every actor returns `{query, file, uri, compiled}`. Because the shape is uniform, dispatch, truncation, and persistence are all generic code that does not branch per tool.

### Skills

A skill is a **directory**, not a class or a registered function:

```
~/.pipali/skills/<skill-name>/
  SKILL.md          (required: YAML frontmatter + markdown body)
  scripts/          (optional, may carry its own package.json)
  references/       (optional)
  assets/           (optional)
```

The in-memory representation is deliberately tiny — name, description, location, visibility. That is all the system tracks.

- **Discovery** (`src/server/skills/loader.ts`) scans the skills directory, validates each `SKILL.md` frontmatter (directory name must match the declared name, name matches a slug regex with a 64-character cap, description between 1 and 1024 characters), and returns both the valid skills and the validation errors. Results are cached in a module-level variable.
- **Builtin skills** ship inside the repository and are copied into the user's skills directory on first run, handling both the development filesystem case and the compiled-binary embedded-asset case, and **never overwriting user edits**.
- **Invocation has no dedicated tool.** This is the key finding. Skills are formatted as XML and injected into the system prompt with only their name, description, and filesystem location. When the model judges a skill relevant, it calls the ordinary `view_file` tool on that location to read the full instructions, then runs `scripts/*` through `shell_command` and reads `references/*` through `view_file` or `grep_files`. A skill is content, not a code path.
- **Selection is pure model judgement.** No router, no embedding match, no keyword matcher chooses a skill.
- **Skill dependencies** declared in `scripts/package.json` are installed automatically at skill-install time, so a skill can carry its own dependency tree.

### End-to-end tool execution flow

1. A WebSocket `message` command resolves or creates a conversation, creates a session with fresh confirmation preferences, and hands off to the run executor.
2. The run executor builds a confirmation context whose callback publishes to the conversation event bus and awaits a client answer.
3. The research runner loads the stored conversation trajectory (an ATIF-style JSON structure held in the database), drives the director's async generator, and persists each step — system, user, agent, tool calls, observations — as it streams to the UI.
4. The **director** is the agent loop. `buildSystemPrompt()` assembles persona, skills XML, and environment context. `pickNextTool()` calls the model with the full tool list — builtin actors plus MCP tool definitions, with search-based deferred loading when the MCP tool set is large — and parses returned function calls. `executeTool()` dispatches by name: a name containing the MCP delimiter goes to the MCP path, everything else hits a switch over actor functions, each receiving an execution context carrying the confirmation service, conversation id, user, and abort signal. `executeToolsInParallel()` races all calls from one turn against the abort signal so an interrupt cleanly marks pending calls as interrupted. The loop continues until the model answers without tool calls, or an iteration cap fires.
5. A tool reaches the operating system, its output is captured and truncated, and the result becomes an observation in the trajectory, fed back as history on the next model call.

## 4. Why the architecture works

**One component owns the loop.** The director is the only place that decides what happens next. Prompt assembly, model invocation, dispatch, and termination all live together, so there is exactly one place to look when the agent misbehaves and exactly one place to change iteration policy.

**One component owns each dangerous capability.** All shell execution is one file. All confirmation is one service. All sandbox policy is one config module. Auditing "what can this system do to my machine" means reading three files.

**Uniform result shapes make the generic layers genuinely generic.** Because actors agree on a result envelope, truncation, persistence, and streaming were written once.

**Progressive disclosure solves the context-budget problem twice with one idea.** Skills are advertised by name, description, and path; large MCP tool sets are advertised through a search tool. Both defer the expensive content until the model asks for it. The same principle, applied at two layers, is why a system with many skills and many MCP servers still fits in a prompt.

**Errors are data, not exceptions.** Returning structured failure strings to the model rather than throwing is what allows the agent to recover — retry in direct mode, fix the path, shorten the command — instead of the run dying.

## 5. Trade-offs

**Model self-reported risk is the primary gate.** Both shell commands (`operation_type` of `read-only`/`write-only`/`read-write`) and MCP tool calls (`operation_type` of `safe`/`unsafe`) rely on the model classifying its own action, and that classification drives the confirmation decision. Unspecified defaults to requiring confirmation, which is the right default, but the design's safety still rests on model honesty and accuracy rather than deterministic analysis. This is convenient — static analysis of an arbitrary shell string is genuinely hard — but it is the wrong thing to make load-bearing on its own.

**Sandbox and confirmation are alternatives, so each command gets exactly one protection.** A sandboxed command is never confirmed; a confirmed command is never sandboxed. There is no defence in depth for the highest-risk operations.

**MCP child processes run outside the sandbox.** They are spawned as ordinary child processes over stdio transport. The bundled browser-automation server — the component that performs the most desktop-like actions in the whole system — is therefore contained only by the confirmation system, which is in turn driven by the model's own safe/unsafe self-report. This is the clearest gap in an otherwise sandboxed-by-default design.

**Per-platform security posture differs sharply.** Full OS containment on macOS and Linux, none on Windows.

**Skill selection quality is entirely a prompt-engineering problem.** With no router, adding many skills eventually degrades selection accuracy and there is no mechanism to compensate other than writing better descriptions.

**Filesystem tools have no OS abstraction.** Path handling is ad hoc, which is fine until it is not.

## 6. What PSOK should adopt

- **A single confirmation service, transport-agnostic, with risk levels and persisted per-operation skip-keys.** This is the right shape and PSOK should copy it closely.
- **A sensitive-path denylist that forces confirmation independently of any sandbox setting.**
- **OS-native sandboxing as a real execution mode**, with declarative allow/deny path and network policy, and honest documentation that Windows does not get it.
- **One component owning shell execution**, capturing stdout, stderr, and exit code, clamping timeouts internally, and returning structured results for every failure rather than throwing.
- **Background execution with a log file and pid**, so long-running commands do not block the loop — but with a lower concurrency cap than 10, since PSOK is a single-user system.
- **Central output truncation** in the loop, not per tool.
- **A uniform tool-result envelope** so dispatch, logging, and truncation stay generic.
- **The skill model essentially unchanged**: a directory with `SKILL.md`, discovered by scanning, validated at load, advertised by name and description and path, read through the ordinary file tool, executed through the ordinary shell tool. No dedicated invoke-skill tool. Builtin skills seeded on first run without clobbering user edits.
- **Progressive disclosure as a general principle** for anything that would otherwise consume prompt budget proportional to installed capability count.
- **One component owning the agent loop**, with prompt assembly, dispatch, and termination policy together.

## 7. What PSOK should avoid

- **Making model self-classification the primary permission gate.** PSOK should instead derive a static risk floor from the tool identity and operation, and allow the model's self-report only to *escalate* that floor, never to lower it. The self-report remains useful precisely where static analysis cannot reach — arbitrary shell strings and opaque MCP calls — but it stops being the whole defence.
- **Treating sandbox and confirmation as mutually exclusive.** PSOK should be free to require both for genuinely destructive operations.
- **Leaving MCP servers entirely outside the containment story.** PSOK cannot sandbox arbitrary MCP servers either, but it can add a cheap guardrail Pipali lacks: require explicit confirmation on the first call to any newly configured MCP server, establishing trust once per server rather than never.
- **Parallel tool execution by default.** Pipali runs all of a turn's tool calls concurrently. For a single-user system doing filesystem and shell mutations, that raises correctness risk (file races, interleaved writes) for very little wall-clock benefit at this scale. PSOK should run sequentially by default and make parallelism opt-in.
- **A browser-automation MCP server auto-installed on first run.** Convenient, but it silently grants a broad and weakly contained capability before the user has asked for it.
- **Advertising a tool parameter the implementation then silently clamps** (the timeout schema advertising 300 seconds while the code enforces 60). The model reasons about the advertised contract; the contract should be true.

## 8. Relevant source files inspected

| Path | Responsibility |
|---|---|
| `CONTRIBUTING.md` | Architecture overview and diagrams; accurate against the code |
| `src/server/processor/director/index.ts` | The agent loop: prompt assembly, tool selection, dispatch, parallel execution, truncation |
| `src/server/processor/research-runner.ts` | Trajectory persistence and streaming around the director |
| `src/server/events/run-executor.ts` | Run lifecycle and confirmation context construction |
| `src/server/routes/ws/commands/message.ts` | WebSocket entry point, conversation and session setup |
| `src/server/routes/ws/confirmation-manager.ts` | Confirmation transport binding over the conversation event bus |
| `src/server/processor/confirmation/confirmation.service.ts`, `confirmation.types.ts` | Risk levels, skip-key persistence, transport-agnostic callback |
| `src/server/security/path-validator.ts` | Sensitive-path regex list |
| `src/server/processor/actor/shell_command.ts` | The only shell executor: modes, capture, timeout, sandbox integration |
| `src/server/processor/actor/{read_file,list_files,grep_files,edit_file,write_file}.ts` | Filesystem tools |
| `src/server/events/background-processes.ts` | Background execution, log files, process termination |
| `src/server/sandbox/{config,index,settings}.ts` | Declarative sandbox policy, Seatbelt/Bubblewrap wrapper, persisted settings |
| `src/server/skills/{types,loader,index,utils}.ts` | Skill model, discovery and validation, builtin seeding, prompt formatting |
| `src/server/skills/builtin/skill-creator/SKILL.md` | The meta-skill the agent reads when authoring skills |
| `src/server/processor/mcp/{manager,client}.ts` | MCP tool execution, confirmation mode, stdio transport spawning |
| `src/server/init.ts` | First-run bundled MCP server installation |
