# PSOK Architecture Research

This directory records targeted architectural research into three existing open-source projects, carried out before any PSOK code was written. The goal was never a general review of these projects. Each one was studied for exactly one concern that PSOK needs to solve, and the research stops at the point where the architectural lesson is clear.

## Why these three projects

PSOK needs to do three fundamentally different kinds of thing well, and each of these projects has already solved one of them in production:

| Project | Researched for | Central question |
|---|---|---|
| [Pipali](pipali.md) | Computer interaction, shell execution, skills, tool execution | How should PSOK give an AI agent controlled access to the user's computer, filesystem, and terminal while keeping those capabilities modular and secure? |
| [Khoj](khoj.md) | Database, storage, documents, retrieval, memory | How should PSOK store the user's personal data, documents, conversations, memories, and embeddings so they are queryable, extensible, and suitable for AI retrieval? |
| [LibreChat](librechat.md) | MCP connectivity, external tools, model providers, provider abstraction | How should PSOK build a unified AI runtime that uses multiple third-party and local models and connects to external tools through MCP, without coupling the core application to any one provider? |

## What each document contains

Every research document follows the same structure:

1. What was investigated
2. Relevant architecture
3. Important implementation details
4. Why the architecture works
5. Trade-offs
6. What PSOK should adopt
7. What PSOK should avoid
8. Relevant source files inspected

No source code from these projects is copied into PSOK's documentation. The documents record architectural conclusions and cite the files where each conclusion came from, so any claim can be re-verified against the original repository.

## Repositories inspected

- Pipali: `/home/wayne/Documents/GitHub/pipali` — Bun + Hono backend, React frontend, Tauri desktop wrapper
- Khoj: `/home/wayne/Documents/GitHub/khoj` — Python, Django ORM + FastAPI, PostgreSQL with pgvector
- LibreChat: `/home/wayne/Documents/GitHub/LibreChat` — Node monorepo. Note that this checkout is a heavily extended enterprise fork with substantially more MCP machinery than upstream, so file references are specific to this checkout.

PSOK itself is being built in **Python (FastAPI backend) with a React frontend**. None of the three projects shares that exact stack, which is deliberate: the value taken from them is architectural, not code-level, and every conclusion below is expressed in terms that survive the language change.

## What PSOK takes from each, in one paragraph each

**From Pipali**, PSOK takes the shape of safe local execution: a single transport-agnostic confirmation service that gates dangerous operations by risk level with persisted "don't ask again" preferences; OS-native sandboxing (Seatbelt on macOS, Bubblewrap on Linux) as an execution mode distinct from confirmation-gated direct execution; a single shell-execution component that never throws at the agent but returns structured results for every failure mode; and the insight that skills are not a separate execution mechanism at all, just markdown directories surfaced by progressive disclosure and consumed through the ordinary file and shell tools. PSOK also takes Pipali's clearly identified weaknesses as things to fix rather than copy — chiefly that model self-reported risk classification is the *only* gate, and that MCP child processes escape the sandbox entirely.

**From Khoj**, PSOK takes the data and retrieval pipeline: content-hash-based incremental indexing so re-syncing an unchanged vault costs nothing; chunking with heading prefixes and a stable corpus identifier tying chunks back to their source; a configurable embedding layer that can be local or remote behind one interface; and above all the two-tier memory design, where the session transcript is one tier and an LLM-curated long-term fact store, updated by a structured create/supersede diff after each turn, is the other. PSOK deliberately diverges from Khoj on two points: conversations become normalized per-message rows rather than one JSON blob, and original document bytes stay on the filesystem rather than being discarded after text extraction.

**From LibreChat**, PSOK takes the provider abstraction almost wholesale: a single initialize-function contract that every provider adapter implements, a registry mapping provider names to adapters, and a fallback where any unrecognized provider name resolves to a generic OpenAI-compatible adapter driven by config. That last detail is what makes Ollama, vLLM, LM Studio, NVIDIA NIM, Groq, and OpenRouter free to support. PSOK also takes the principle that provider quirks (Anthropic's thinking budgets, OpenAI's reasoning-versus-tools constraints, Gemini's restricted function-calling schemas) are absorbed inside each adapter and never leak outward. From LibreChat's MCP layer PSOK takes composite tool-key namespacing, uniform result normalization before results reach the agent, SSRF protection on URL transports, and per-server circuit breaking — while explicitly rejecting the multi-tenant machinery (on-behalf-of token exchange, cluster leader election, Redis-backed shared caches, admin-versus-user server tiers) that only exists because LibreChat serves many users who are not the operator.
