# AI Runtime

The AI runtime is everything between "the agent loop wants a model response" and "a specific provider's API returned tokens." It has two parts: the **provider abstraction** (how PSOK talks to any model without knowing which one) and the **agent loop** (the component that owns the reason/act/observe cycle).

## The provider abstraction

### The contract

Every provider adapter implements one function. That is the whole abstraction — no base class to inherit, no lifecycle to implement, no plugin registration protocol.

```
initialize(provider_config, model_parameters) -> ResolvedModel

ResolvedModel:
    provider          str            # canonical provider name
    model             str            # concrete model id
    client            ChatClient     # something the loop can call
    capabilities      Capabilities   # what this model can actually do
    normalize_tools   callable       # PSOK tool schemas -> provider tool schemas
```

`Capabilities` declares what the loop is allowed to attempt: whether tools are supported, whether streaming works, whether images can be sent, the context window size, and whether the model has a reasoning or thinking mode. The loop reads capabilities and adapts — it does not guess from the model name.

`ChatClient` exposes a single method taking a normalized message list, a tool list, and parameters, and returning a normalized response containing text, tool calls, a stop reason, and usage. Streaming is the same shape yielded incrementally.

The reason the contract is this small is the same reason LibreChat's equivalent works: an abstraction nobody is tempted to bypass is an abstraction that stays true. There is no place to put a provider special case except inside a provider.

### The registry and the fallback

```
PROVIDER_REGISTRY = {
    "openai":            initialize_openai,
    "anthropic":         initialize_anthropic,
    "google":            initialize_google,
    "ollama":            initialize_ollama,
    "openai-compatible": initialize_openai_compatible,
}
```

Resolution works as follows. A conversation stores a provider and model as strings. The runtime looks up the provider name in the registry. **If it is not there, the name is looked up in the user's `providers.yaml`, and unless that entry declares a different native provider, it resolves to the OpenAI-compatible adapter.**

That fallback is the single most valuable idea taken from LibreChat, and it is worth being explicit about what it buys. Because most of the industry converged on the OpenAI chat-completions wire format, one generic adapter plus a base URL covers:

- **Ollama** — `http://localhost:11434/v1`
- **vLLM**, **LM Studio**, **llama.cpp server**, **text-generation-webui** — any local inference server
- **NVIDIA NIM**, **Groq**, **OpenRouter**, **Together**, **Fireworks**, **DeepSeek**, **Mistral** — hosted providers

None of these requires an adapter. Supporting a new one is adding four lines to a config file. PSOK ships four native adapters and gets an open-ended set of providers for free.

Example `providers.yaml`:

```yaml
providers:
  - name: openai
    api_key_ref: psok/openai            # keychain reference, not a key
  - name: anthropic
    api_key_ref: psok/anthropic
  - name: ollama
    base_url: http://localhost:11434/v1
    # no key needed
  - name: nvidia-nim
    base_url: https://integrate.api.nvidia.com/v1
    api_key_ref: psok/nvidia
    provider: openai-compatible          # implied, but may be explicit
  - name: my-vllm-box
    base_url: http://192.168.1.40:8000/v1
    api_key_ref: psok/vllm
```

**`api_key_ref` is a keychain reference, never a key.** No secret appears in this file. See [security.md](security.md).

### Why Ollama gets a named adapter anyway

Ollama speaks the OpenAI format and could ride the fallback. It gets a thin adapter that *extends* the OpenAI-compatible one for two reasons specific to local models: native model management calls (list installed models, pull a model), which the first-run experience needs, and native embeddings, which the retrieval pipeline uses. The adapter is a small subclass, not a parallel implementation.

### Where provider quirks live

**Every provider-specific behaviour lives inside its adapter and is invisible above it.** The known cases, all confirmed in LibreChat's implementation:

- **Google/Gemini** rejects JSON Schema unions and non-string enums in function declarations that OpenAI and Anthropic accept. The Google adapter sanitizes tool schemas on the way out. Note that this is a *tool-schema* quirk, not a parameter quirk — provider differences are not confined to model settings.
- **Anthropic** takes extended thinking as a native enabled-with-budget block, with model-version differences and a budget that must not exceed max tokens. The adapter maps PSOK's generic `thinking_budget` and clamps it.
- **OpenAI** maps PSOK's generic `reasoning_effort` into its reasoning object, and some models reject reasoning combined with function tools on chat-completions, requiring the Responses API instead. The adapter routes accordingly.
- **OpenAI-compatible endpoints** frequently do not implement structured multimodal content blocks. The adapter defaults to the simpler content format. Some also ignore `stream: true` and answer with an ordinary JSON body; a stream that carries nothing is not an empty answer, so the adapter asks again without streaming rather than reporting silence.
- **Message translation is per adapter, including this one.** PSOK's own message rows are not the chat-completions wire shape: tool calls need `type: "function"` and `arguments` as a JSON string, and the `tool_name` and `is_error` columns PSOK keeps for itself do not belong on the wire. Each adapter converts on the way out.

PSOK's common parameter surface is deliberately small: `temperature`, `max_tokens`, `reasoning_effort` (none/low/medium/high), `thinking_budget`, `stop`, `seed`. Anything a provider does not support is dropped by its adapter, which reports the drop through capabilities rather than failing.

**The test for whether this boundary is holding:** grep the agent loop and tool registry for provider names. If a provider name appears outside `runtime/providers/`, the abstraction has leaked.

### Switching models

The active provider and model are a string field on the conversation. The loop resolves the adapter **fresh on every turn**, so switching is changing a string — no restart, no re-initialization, and it can happen mid-conversation. "Use Claude for this task" is a tool call or a UI action that updates the field.

Different roles can use different models simultaneously, all through the same registry:

| Role | Typical default |
|---|---|
| Main conversation and tool calling | User's choice; capability-gated (see below) |
| Memory fact extraction | Small, cheap, local |
| Search-query generation | Small, cheap, local |
| Embeddings | Local (`nomic-embed-text` via Ollama) |

### The local-first tension, resolved

PSOK's posture is local-first — it is a personal knowledge system holding the user's private documents and correspondence. But small local models are measurably worse at structured tool calling than frontier cloud models, and the agent loop depends entirely on structured tool calling.

Resolution: **local-first governs data-heavy background roles strongly, and the main conversational model by preference but not by force.** Embeddings and memory extraction default local, because they touch every document and every turn. For the main model, first-run setup detects whether a tool-calling-capable local model is available and either recommends pulling one or prompts for a cloud API key — rather than silently defaulting to a model that will fail at the loop and make PSOK look broken. Recorded as [ADR-0013](decisions/0013-local-first-ai-default-posture.md).

### No LangChain

PSOK calls the official SDKs (`openai`, `anthropic`, `google-genai`) directly behind the adapter interface. The interface *is* PSOK's abstraction; a framework on top of it would be a second one.

LangChain earns its cost when you need chain composition, a large integration surface, or swappable orchestration. PSOK runs one conversation at a time with one loop, and every provider integration it needs is a hundred lines against a well-documented SDK. Adopting the framework would mean debugging through its abstractions and inheriting its upgrade cadence to solve a problem PSOK does not have. Recorded in [ADR-0001](decisions/0001-ai-provider-abstraction.md).

## The agent loop

One component — the **Director** — owns the entire cycle. Nothing else decides what happens next.

### The cycle

```
    ┌─────────────────────────────────────────┐
    │ 1. ASSEMBLE                             │
    │    persona + skills catalogue           │
    │    + tool catalogue + retrieved context  │
    │    + memories + budgeted history         │
    └───────────────────┬─────────────────────┘
                        ▼
    ┌─────────────────────────────────────────┐
    │ 2. CALL      resolve adapter, invoke     │
    └───────────────────┬─────────────────────┘
                        ▼
              ┌─────────┴─────────┐
              │ tool calls?       │
              └──┬─────────────┬──┘
             no  │             │ yes
                 ▼             ▼
    ┌──────────────┐   ┌────────────────────────┐
    │ 5. FINISH    │   │ 3. DISPATCH             │
    │ persist,     │   │    permission gate →     │
    │ extract      │   │    execute → normalize → │
    │ memory,      │   │    truncate → audit log  │
    │ return       │   └────────────┬─────────────┘
    └──────────────┘                ▼
                       ┌────────────────────────┐
                       │ 4. OBSERVE              │
                       │    append results,      │
                       │    check guards, loop ──┼──┐
                       └────────────────────────┘  │
                                    ▲              │
                                    └──────────────┘
```

**1. Assemble.** The system prompt is built fresh each turn: persona and environment (OS, date, timezone, workspace root), the skills catalogue as name/description/path triples, the tool catalogue as JSON Schemas, retrieved document context, recalled memories, and conversation history truncated oldest-first to fit the model's budget. Budgeting is arithmetic against the model's declared context window, not a fixed message count — Khoj's approach, and the reason a small local model and a large cloud model can run the same loop.

**2. Call.** The adapter is resolved from the conversation's provider string and invoked with normalized messages, tools, and parameters.

**3. Dispatch.** Every tool call goes through the same path: look up the tool, evaluate the permission gate (which may pause the loop for user confirmation), execute, normalize the result into the standard envelope, truncate if oversized, and write an audit-log row. No tool bypasses this path, including MCP tools and integration tools.

**4. Observe.** Results append to the trajectory. Guards are checked: maximum iterations, cumulative token budget, wall-clock limit, repeated-identical-call detection. Any guard trip ends the loop with an explanatory message rather than silently.

**5. Finish.** When the model responds without tool calls, the trajectory is persisted and a post-turn memory extraction may run.

### Sequential by default

Pipali executes all of a turn's tool calls concurrently. PSOK does not, by default.

For a single-user system whose tools mutate the local filesystem, run shell commands, and write to one SQLite database, concurrent execution introduces real correctness risk — interleaved writes to the same file, ordering-dependent shell commands, lock contention — in exchange for wall-clock savings that barely register at this scale. Parallel execution is an opt-in configuration flag for read-only tool sets. Recorded in [ADR-0016](decisions/0016-agent-loop-ownership-and-concurrency.md).

### Errors are results

No tool failure raises out of the dispatcher. Every failure — timeout, permission denial, network error, malformed arguments, MCP server unreachable — becomes a descriptive string in the result envelope with an error flag set. The model reads it and can react: retry differently, ask the user, or explain what went wrong.

This is Pipali's most valuable implementation habit and LibreChat's most valuable error-handling habit, and they agree. Specificity matters: "this MCP server requires authentication" and "OAuth is not configured for this server" lead to different useful next actions, while "tool call failed" leads to none.

### What the loop emits

The loop yields events rather than returning a result, so an interface can show a
turn as it happens. The API forwards them verbatim as SSE frames.

| Event | Data | Meaning |
|---|---|---|
| `assistant_delta` | `text` | A fragment of the answer. Append it. |
| `reasoning_delta` | `text` | The model's thinking. Render separately or hide — never as the answer. |
| `assistant_text` | `text` | The whole answer at once, from a provider that cannot stream. |
| `tool_call` | `name`, `arguments` | A tool is about to run. It may pause here for confirmation. |
| `confirmation_required` | `request_id`, `tool_name`, `operation_key`, `risk`, `reason`, `arguments` | The turn is suspended waiting for this decision. Answer it with `request_id`. |
| `tool_result` | `name`, `content`, `is_error` | What it returned. |
| `warning` | `message` | The turn continues but something was lost, e.g. a truncated stream. |
| `guard` | `reason` | A limit, or the user's stop request, ended the turn. |
| `error` | `message` | The turn failed. Always the last event. |
| `done` | `text`, `iterations` | The turn finished. |

**The answer arrives exactly once.** A streaming provider produces
`assistant_delta` chunks and no `assistant_text`; a non-streaming one produces
`assistant_text` and no deltas. `done.text` repeats the final answer for
convenience and must not be rendered by an interface that already showed it.
The rule is "was the answer delivered as deltas", not "was the streaming path
taken" — an adapter may fall back to a plain call inside `stream()` when the
endpoint ignores `stream: true`, and that answer still arrives as
`assistant_text`.

**A suspended turn says so.** `confirmation_required` is emitted before the
loop blocks, carrying the id the decision is answered with. An interface can
poll `GET /api/confirmations` instead, but then it has to guess which
`tool_call` produced a prompt and which did not — the event removes the guess.

**Failures are events, not exceptions.** Nothing raises out of the loop — an
unconfigured provider, a prompt-assembly failure and a dead database all become
a final `error` event. This matters most over SSE, where the response headers
are long since sent: an exception there closes a 200 response mid-body, which a
browser cannot tell apart from a dropped connection.

### Interruption and confirmation

Both suspend the loop mid-turn. A confirmation request pauses at dispatch, surfaces through the transport-agnostic confirmation service, and resumes on the user's answer — with a long timeout so scheduled and unattended runs remain approvable later.

A user interrupt is a second request rather than a dropped connection, because a dropped connection is exactly what it must be distinguishable from: closing the response leaves the loop running. `POST /api/conversations/{id}/turn/stop` sets an event the loop reads before its next model call and while a dispatch is in flight; the in-flight call is cancelled — including one suspended on a confirmation, which would otherwise hold the gate for its full timeout — and marked interrupted in the trajectory, so the history stays truthful about what did and did not run. The turn ends with a `guard` event rather than silence.

### What the loop persists

Every turn writes normalized message rows (user, assistant, and tool messages, with tool calls and results as JSON columns) and, for each tool call, an audit-log row recording the tool, its source, arguments, result summary, risk level, confirmation decision, duration, and outcome.

Two tables rather than one because their retention policies differ: conversation history is the user's data and is kept, while the audit log is operational and prunable. Recorded in [ADR-0017](decisions/0017-conversation-message-persistence-model.md).

## Component boundaries

| Component | Responsibility |
|---|---|
| `runtime/providers/*` | One adapter per provider; all quirks; all credential resolution |
| `runtime/registry.py` | Name to adapter resolution, including the OpenAI-compatible fallback |
| `runtime/types.py` | `ResolvedModel`, `Capabilities`, normalized message and response shapes |
| `agent/director.py` | The loop and its guards; the only owner of the cycle |
| `agent/prompt.py` | Prompt assembly and token budgeting |
| `tools/registry.py` | The flat namespace and dispatch (see [components.md](components.md)) |

The Director imports the runtime and the tool registry. Neither imports the Director. Provider modules import neither.
