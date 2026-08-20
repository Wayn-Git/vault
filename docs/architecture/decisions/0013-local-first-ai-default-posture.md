# ADR-0013: Local-First AI Default Posture

## Status

Proposed

## Context

PSOK is a personal knowledge system holding private documents and correspondence, which argues for a strong local-first, privacy-preserving default. But small local models are measurably weaker at structured tool calling than frontier cloud models, and the entire agent loop depends on reliable tool calling. See [ai-runtime.md](../ai-runtime.md#the-local-first-tension-resolved).

## Decision

Apply local-first as a strong default for data-handling-heavy background roles — embeddings and memory fact extraction default to a local model via Ollama — but not as a forced default for the main conversational/tool-calling model. First-run setup detects whether a tool-calling-capable local model is available and prompts the user to pull one or configure a cloud provider key, rather than silently defaulting to a local model likely to produce unreliable agent behavior.

## Alternatives Considered

- **Force local models everywhere, including the main conversational model.** Rejected: would make the agent loop unreliable out of the box for most users on typical hardware, contradicting the product's basic function.
- **Default to cloud providers everywhere for reliability.** Rejected: undermines the privacy-first positioning for data-handling roles (embeddings, memory) where local models are perfectly adequate and the privacy benefit is real and constant.

## Trade-offs

Requires first-run capability detection logic (does a tool-calling-capable local model exist, is Ollama installed) rather than a single flat default — added complexity accepted because the alternative (a silent bad default) directly damages first-run experience quality.

## Consequences

Embeddings and memory extraction are private by default regardless of the main model choice. The main model's provider is a deliberate, informed user choice rather than an assumption, surfaced explicitly at setup.
