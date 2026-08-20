# ADR-0016: Agent Loop Ownership & Concurrency

## Status

Proposed

## Context

Something must own the reason/act/observe cycle. Pipali's Director executes all of a turn's tool calls concurrently via a Promise.allSettled-style race. PSOK's tools frequently mutate local filesystem state and a single SQLite database. See [ai-runtime.md](../ai-runtime.md#the-agent-loop).

## Decision

One component, the Director, owns the entire loop: prompt assembly, model invocation, dispatch, observation, and termination. Tool calls within a turn execute sequentially by default; parallel execution is an opt-in configuration flag intended for read-only tool sets.

## Alternatives Considered

- **Concurrent tool execution by default, as in Pipali.** Rejected as the default: for a single-user system where tools commonly mutate the filesystem or write to the same database, concurrent execution introduces real correctness risk (file races, interleaved writes, lock contention) for wall-clock savings that barely register at PSOK's scale.
- **Splitting loop responsibilities across multiple components** (a separate dispatcher-owning component, a separate prompt-assembly service invoked independently). Rejected: fragments the one place to look when the agent misbehaves, the exact benefit a single owning component provides.

## Trade-offs

Sequential-by-default execution is slower wall-clock than full concurrency when a turn genuinely requests several independent read-only operations; the opt-in parallel flag exists specifically to recover that case without making it the default risk profile.

## Consequences

A tension this decision surfaces and resolves: background integration sync workers still write concurrently with an in-flight conversation turn from outside the loop. This is handled at the data layer (WAL mode, short transactions, idempotent upserts — see [data-model.md](../data-model.md#consistency-and-concurrency)), not by the loop itself, since the loop's sequential guarantee only covers what it directly dispatches.
