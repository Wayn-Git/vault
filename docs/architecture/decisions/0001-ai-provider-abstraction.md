# ADR-0001: AI Provider Abstraction

## Status

Proposed

## Context

PSOK must support OpenAI, Anthropic, Google, NVIDIA, Ollama, and other providers, switchable at runtime, without the core agent loop or tool system knowing which provider is active. It must also support local models without treating them as a special case. See [ai-runtime.md](../ai-runtime.md).

## Decision

Adopt a minimal adapter contract — one function per provider mapping provider config and generic model parameters into a common `ResolvedModel` (client, capabilities, tool-schema normalizer) — held in a registry keyed by provider name. Any provider name not in the registry resolves through a user-editable `providers.yaml` entry to a generic OpenAI-compatible adapter by default. Provider-specific quirks (Anthropic thinking budgets, OpenAI reasoning/tool-use constraints, Gemini schema restrictions) are translated entirely inside each adapter. No LangChain or similar orchestration framework; official vendor SDKs are called directly behind the adapter interface.

## Alternatives Considered

- **A full framework (LangChain/LlamaIndex) as the abstraction layer.** Rejected: PSOK runs one conversation at a time with no chain composition, and the framework's abstraction surface exceeds the need, adding a dependency PSOK cannot fully control.
- **A bespoke adapter per named provider, including Ollama and NVIDIA NIM.** Rejected: most non-frontier and local providers already speak the OpenAI chat-completions format; writing bespoke adapters for each duplicates work the fallback handles for free.
- **No abstraction — call each SDK directly from the agent loop.** Rejected: this is exactly the coupling the brief asks PSOK to avoid, and it would make provider-specific bugs invisible until they surface deep in loop code.

## Trade-offs

The fallback adapter cannot expose capabilities a provider offers outside the OpenAI-compatible surface (for instance, a local server's native embedding endpoint) without a thin provider-specific extension, as done for Ollama. Owning the loop and adapters directly means PSOK carries maintenance for provider API changes itself rather than inheriting a framework's updates — accepted as the right trade for a smaller, fully understood core.

## Consequences

Adding a new OpenAI-compatible provider is a config change, not a code change. Provider-specific behavior is auditable by reading one adapter module. The agent loop and tool registry can be tested against a mock adapter without any real provider.
